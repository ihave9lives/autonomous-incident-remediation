package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"math"
	"os"
	"os/signal"
	"syscall"
	"time"
)

type MetricPoint struct {
	Timestamp int64   `json:"timestamp"`
	Value     float64 `json:"value"`
	Service   string  `json:"service"`
	Metric    string  `json:"metric"`
}

type LogEntry struct {
	Timestamp int64  `json:"timestamp"`
	Level     string `json:"level"`
	Message   string `json:"message"`
	Service   string `json:"service"`
}

type AnomalyAlert struct {
	Timestamp   int64   `json:"timestamp"`
	Service     string  `json:"service"`
	Metric      string  `json:"metric"`
	Detector    string  `json:"detector"`
	Score       float64 `json:"score"`
	Threshold   float64 `json:"threshold"`
	Value       float64 `json:"value"`
	Description string  `json:"description"`
}

type EWMAConfig struct {
	Alpha       float64 `json:"alpha"`
	Threshold   float64 `json:"threshold"`
	WindowSize  int     `json:"window_size"`
	MinSamples  int     `json:"min_samples"`
}

type EntropyConfig struct {
	WindowSize  int     `json:"window_size"`
	Threshold   float64 `json:"threshold"`
	MinSamples  int     `json:"min_samples"`
}

type Config struct {
	EWMA    EWMAConfig    `json:"ewma"`
	Entropy EntropyConfig `json:"entropy"`
	Metrics struct {
		Endpoint string `json:"endpoint"`
		Interval int    `json:"interval"`
	} `json:"metrics"`
	Logs struct {
		Endpoint string `json:"endpoint"`
		Interval int    `json:"interval"`
	} `json:"logs"`
	AlertEndpoint string `json:"alert_endpoint"`
}

func defaultConfig() Config {
	return Config{
		EWMA: EWMAConfig{
			Alpha:      0.3,
			Threshold:  3.0,
			WindowSize: 100,
			MinSamples: 10,
		},
		Entropy: EntropyConfig{
			WindowSize:  50,
			Threshold:   2.5,
			MinSamples:  20,
		},
		AlertEndpoint: "http://localhost:8080/alerts",
	}
}

type EWMADetector struct {
	config   EWMAConfig
	values   []float64
	mean     float64
	variance float64
	count    int
}

func NewEWMADetector(config EWMAConfig) *EWMADetector {
	return &EWMADetector{
		config: config,
		values: make([]float64, 0, config.WindowSize),
	}
}

func (d *EWMADetector) Update(value float64) (bool, float64, float64) {
	d.values = append(d.values, value)
	if len(d.values) > d.config.WindowSize {
		d.values = d.values[1:]
	}

	if d.count == 0 {
		d.mean = value
		d.variance = 0
		d.count = 1
		return false, 0, d.mean
	}

	alpha := d.config.Alpha
	oldMean := d.mean
	d.mean = alpha*value + (1-alpha)*d.mean
	d.variance = alpha*(value-oldMean)*(value-oldMean) + (1-alpha)*d.variance
	d.count++

	if d.count < d.config.MinSamples {
		return false, 0, d.mean
	}

	stdDev := math.Sqrt(d.variance)
	if stdDev == 0 {
		return false, 0, d.mean
	}

	zScore := math.Abs(value - d.mean) / stdDev
	isAnomaly := zScore > d.config.Threshold

	return isAnomaly, zScore, d.mean
}

type EntropyDetector struct {
	config EntropyConfig
	window []LogEntry
}

func NewEntropyDetector(config EntropyConfig) *EntropyDetector {
	return &EntropyDetector{
		config: config,
		window: make([]LogEntry, 0, config.WindowSize),
	}
}

func (d *EntropyDetector) Update(entry LogEntry) (bool, float64) {
	d.window = append(d.window, entry)
	if len(d.window) > d.config.WindowSize {
		d.window = d.window[1:]
	}

	if len(d.window) < d.config.MinSamples {
		return false, 0
	}

	levelCounts := make(map[string]int)
	for _, e := range d.window {
		levelCounts[e.Level]++
	}

	total := float64(len(d.window))
	entropy := 0.0
	for _, count := range levelCounts {
		p := float64(count) / total
		if p > 0 {
			entropy -= p * math.Log2(p)
		}
	}

	maxEntropy := math.Log2(float64(len(levelCounts)))
	if maxEntropy == 0 {
		return false, entropy
	}

	normalizedEntropy := entropy / maxEntropy
	isAnomaly := normalizedEntropy > d.config.Threshold

	return isAnomaly, normalizedEntropy
}

func loadConfig(path string) (Config, error) {
	cfg := defaultConfig()
	if path == "" {
		return cfg, nil
	}

	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return cfg, nil
		}
		return cfg, err
	}

	if err := json.Unmarshal(data, &cfg); err != nil {
		return cfg, err
	}

	return cfg, nil
}

func simulateMetrics(cfg Config, ewma *EWMADetector, alerts chan<- AnomalyAlert) {
	ticker := time.NewTicker(time.Duration(cfg.Metrics.Interval) * time.Second)
	defer ticker.Stop()

	baseLatency := 50.0
	trend := 0.0

	for range ticker.C {
		noise := (randFloat64() - 0.5) * 20
		trend += (randFloat64() - 0.5) * 2
		if trend > 50 {
			trend = 50
		}
		if trend < -20 {
			trend = -20
		}

		value := baseLatency + trend + noise
		if value < 1 {
			value = 1
		}

		isAnomaly, score, mean := ewma.Update(value)

		if isAnomaly {
			alert := AnomalyAlert{
				Timestamp:   time.Now().UnixMilli(),
				Service:     "checkout-service",
				Metric:      "http_latency_ms",
				Detector:    "ewma",
				Score:       score,
				Threshold:   cfg.EWMA.Threshold,
				Value:       value,
				Description: fmt.Sprintf("Latency spike detected: %.2fms (mean: %.2fms, z-score: %.2f)", value, mean, score),
			}
			alerts <- alert
			log.Printf("EWMA ALERT: %s", alert.Description)
		}
	}
}

func simulateLogs(cfg Config, entropy *EntropyDetector, alerts chan<- AnomalyAlert) {
	ticker := time.NewTicker(time.Duration(cfg.Logs.Interval) * time.Second)
	defer ticker.Stop()

	levels := []string{"INFO", "WARN", "ERROR", "DEBUG"}
	baseWeights := []float64{0.7, 0.15, 0.05, 0.1}
	errorBurst := false
	burstCounter := 0

	for range ticker.C {
		weights := baseWeights
		if errorBurst {
			weights = []float64{0.1, 0.1, 0.7, 0.1}
			burstCounter++
			if burstCounter >= 5 {
				errorBurst = false
				burstCounter = 0
			}
		} else if randFloat64() < 0.02 {
			errorBurst = true
			burstCounter = 0
		}

		r := randFloat64()
		cumulative := 0.0
		level := "INFO"
		for i, w := range weights {
			cumulative += w
			if r <= cumulative {
				level = levels[i]
				break
			}
		}

		msg := fmt.Sprintf("Request processed latency=%dms", int(50+randFloat64()*100))
		if level == "ERROR" {
			msg = "Failed to process request: connection timeout"
		} else if level == "WARN" {
			msg = "High latency detected, retrying"
		}

		entry := LogEntry{
			Timestamp: time.Now().UnixMilli(),
			Level:     level,
			Message:   msg,
			Service:   "checkout-service",
		}

		isAnomaly, score := entropy.Update(entry)

		if isAnomaly {
			alert := AnomalyAlert{
				Timestamp:   time.Now().UnixMilli(),
				Service:     "checkout-service",
				Metric:      "log_entropy",
				Detector:    "entropy",
				Score:       score,
				Threshold:   cfg.Entropy.Threshold,
				Value:       score,
				Description: fmt.Sprintf("Log entropy burst detected: normalized entropy=%.3f (threshold=%.3f)", score, cfg.Entropy.Threshold),
			}
			alerts <- alert
			log.Printf("ENTROPY ALERT: %s", alert.Description)
		}
	}
}

func alertSender(alerts <-chan AnomalyAlert, endpoint string) {
	for alert := range alerts {
		data, _ := json.Marshal(alert)
		log.Printf("Sending alert to %s: %s", endpoint, string(data))
	}
}

func randFloat64() float64 {
	return float64(time.Now().UnixNano()%1000000) / 1000000.0
}

func main() {
	configPath := flag.String("config", "", "Path to config JSON file")
	flag.Parse()

	cfg, err := loadConfig(*configPath)
	if err != nil {
		log.Fatalf("Failed to load config: %v", err)
	}

	log.Printf("Starting anomaly-daemon with config: %+v", cfg)

	ewma := NewEWMADetector(cfg.EWMA)
	entropy := NewEntropyDetector(cfg.Entropy)

	alerts := make(chan AnomalyAlert, 100)

	go simulateMetrics(cfg, ewma, alerts)
	go simulateLogs(cfg, entropy, alerts)
	go alertSender(alerts, cfg.AlertEndpoint)

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
	<-sigCh

	log.Println("Shutting down...")
	close(alerts)
}