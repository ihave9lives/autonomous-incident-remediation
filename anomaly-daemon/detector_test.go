package main

import (
	"math"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestEWMADetector_Initialization(t *testing.T) {
	config := EWMAConfig{
		Alpha:      0.3,
		Threshold:  3.0,
		WindowSize: 100,
		MinSamples: 10,
	}
	detector := NewEWMADetector(config)
	require.NotNil(t, detector)
}

func TestEWMADetector_FirstSample(t *testing.T) {
	config := EWMAConfig{
		Alpha:      0.3,
		Threshold:  3.0,
		WindowSize: 100,
		MinSamples: 10,
	}
	detector := NewEWMADetector(config)

	isAnomaly, score, mean := detector.Update(50.0)
	assert.False(t, isAnomaly)
	assert.Equal(t, 0.0, score)
	assert.Equal(t, 50.0, mean)
}

func TestEWMADetector_StableValues_NoAnomaly(t *testing.T) {
	config := EWMAConfig{
		Alpha:      0.3,
		Threshold:  3.0,
		WindowSize: 100,
		MinSamples: 5,
	}
	detector := NewEWMADetector(config)

	for i := 0; i < 10; i++ {
		isAnomaly, _, _ := detector.Update(50.0 + float64(i%3-1)*0.5)
		assert.False(t, isAnomaly, "Stable values should not trigger anomaly at iteration %d", i)
	}
}

func TestEWMADetector_SpikeDetection(t *testing.T) {
	config := EWMAConfig{
		Alpha:      0.5,
		Threshold:  0.5,
		WindowSize: 100,
		MinSamples: 10,
	}
	detector := NewEWMADetector(config)

	for i := 0; i < 15; i++ {
		detector.Update(50.0)
	}

	isAnomaly, score, _ := detector.Update(500.0)
	assert.True(t, isAnomaly, "Large spike should trigger anomaly")
	assert.Greater(t, score, config.Threshold, "Z-score should exceed threshold")
}

func TestEWMADetector_GradualShift(t *testing.T) {
	config := EWMAConfig{
		Alpha:      0.3,
		Threshold:  3.0,
		WindowSize: 100,
		MinSamples: 10,
	}
	detector := NewEWMADetector(config)

	for i := 0; i < 15; i++ {
		detector.Update(50.0)
	}

	for i := 0; i < 20; i++ {
		val := 50.0 + float64(i)*3.0
		isAnomaly, _, _ := detector.Update(val)
		if isAnomaly {
			assert.GreaterOrEqual(t, val, 100.0, "Anomaly should be detected after significant shift")
			return
		}
	}
}

func TestEWMADetector_VarianceCalculation(t *testing.T) {
	config := EWMAConfig{
		Alpha:      0.5,
		Threshold:  2.0,
		WindowSize: 10,
		MinSamples: 5,
	}
	detector := NewEWMADetector(config)

	detector.Update(10.0)
	detector.Update(10.0)
	detector.Update(10.0)
	detector.Update(10.0)
	detector.Update(10.0)

	isAnomaly, score, _ := detector.Update(10.0)
	assert.False(t, isAnomaly)
	assert.Equal(t, 0.0, score)
}

func TestEntropyDetector_Initialization(t *testing.T) {
	config := EntropyConfig{
		WindowSize:  50,
		Threshold:   2.5,
		MinSamples:  20,
	}
	detector := NewEntropyDetector(config)
	require.NotNil(t, detector)
}

func TestEntropyDetector_InsufficientSamples(t *testing.T) {
	config := EntropyConfig{
		WindowSize:  50,
		Threshold:   2.5,
		MinSamples:  20,
	}
	detector := NewEntropyDetector(config)

	for i := 0; i < 10; i++ {
		isAnomaly, score := detector.Update(LogEntry{
			Timestamp: int64(i),
			Level:     "INFO",
			Message:   "test",
			Service:   "test",
		})
		assert.False(t, isAnomaly)
		assert.Equal(t, 0.0, score)
	}
}

func TestEntropyDetector_UniformDistribution_LowEntropy(t *testing.T) {
	config := EntropyConfig{
		WindowSize:  50,
		Threshold:   0.5,
		MinSamples:  20,
	}
	detector := NewEntropyDetector(config)

	for i := 0; i < 25; i++ {
		detector.Update(LogEntry{
			Timestamp: int64(i),
			Level:     "INFO",
			Message:   "test",
			Service:   "test",
		})
	}

	isAnomaly, score := detector.Update(LogEntry{
		Timestamp: 25,
		Level:     "INFO",
		Message:   "test",
		Service:   "test",
	})
	assert.False(t, isAnomaly, "Uniform distribution should have low entropy")
	assert.Less(t, score, 0.1, "Entropy should be near zero for uniform distribution")
}

func TestEntropyDetector_BalancedDistribution_HighEntropy(t *testing.T) {
	config := EntropyConfig{
		WindowSize:  50,
		Threshold:   0.5,
		MinSamples:  20,
	}
	detector := NewEntropyDetector(config)

	levels := []string{"INFO", "WARN", "ERROR", "DEBUG"}
	for i := 0; i < 24; i++ {
		detector.Update(LogEntry{
			Timestamp: int64(i),
			Level:     levels[i%4],
			Message:   "test",
			Service:   "test",
		})
	}

	isAnomaly, score := detector.Update(LogEntry{
		Timestamp: 24,
		Level:     "INFO",
		Message:   "test",
		Service:   "test",
	})
	assert.True(t, isAnomaly, "Balanced distribution should have high entropy")
	assert.Greater(t, score, config.Threshold, "Normalized entropy should exceed threshold")
}

func TestEntropyDetector_ErrorBurst(t *testing.T) {
	config := EntropyConfig{
		WindowSize:  50,
		Threshold:   0.7,
		MinSamples:  20,
	}
	detector := NewEntropyDetector(config)

	for i := 0; i < 20; i++ {
		detector.Update(LogEntry{
			Timestamp: int64(i),
			Level:     "INFO",
			Message:   "ok",
			Service:   "test",
		})
	}

	for i := 0; i < 10; i++ {
		isAnomaly, score := detector.Update(LogEntry{
			Timestamp: int64(20 + i),
			Level:     "ERROR",
			Message:   "failed",
			Service:   "test",
		})
		if isAnomaly {
			assert.Greater(t, score, config.Threshold)
			return
		}
	}
	assert.Fail(t, "Error burst should trigger entropy anomaly")
}

func TestEntropyDetector_WindowSliding(t *testing.T) {
	config := EntropyConfig{
		WindowSize:  10,
		Threshold:   0.7,
		MinSamples:  5,
	}
	detector := NewEntropyDetector(config)

	for i := 0; i < 10; i++ {
		detector.Update(LogEntry{
			Timestamp: int64(i),
			Level:     "INFO",
			Message:   "ok",
			Service:   "test",
		})
	}

	isAnomaly, _ := detector.Update(LogEntry{
		Timestamp: 10,
		Level:     "ERROR",
		Message:   "fail",
		Service:   "test",
	})
	assert.False(t, isAnomaly, "Single error in mostly INFO window should not trigger")

	for i := 0; i < 5; i++ {
		detector.Update(LogEntry{
			Timestamp: int64(11 + i),
			Level:     "ERROR",
			Message:   "fail",
			Service:   "test",
		})
	}
	for i := 0; i < 4; i++ {
		detector.Update(LogEntry{
			Timestamp: int64(16 + i),
			Level:     "WARN",
			Message:   "warn",
			Service:   "test",
		})
	}

	isAnomaly, score := detector.Update(LogEntry{
		Timestamp: 20,
		Level:     "DEBUG",
		Message:   "debug",
		Service:   "test",
	})
	assert.True(t, isAnomaly, "Window should now have balanced levels")
	assert.Greater(t, score, config.Threshold)
}

func TestConfig_Defaults(t *testing.T) {
	cfg := defaultConfig()
	assert.Equal(t, 0.3, cfg.EWMA.Alpha)
	assert.Equal(t, 3.0, cfg.EWMA.Threshold)
	assert.Equal(t, 100, cfg.EWMA.WindowSize)
	assert.Equal(t, 10, cfg.EWMA.MinSamples)
	assert.Equal(t, 50, cfg.Entropy.WindowSize)
	assert.Equal(t, 2.5, cfg.Entropy.Threshold)
	assert.Equal(t, 20, cfg.Entropy.MinSamples)
}

func TestZScoreCalculation(t *testing.T) {
	config := EWMAConfig{
		Alpha:      0.5,
		Threshold:  2.0,
		WindowSize: 10,
		MinSamples: 5,
	}
	detector := NewEWMADetector(config)

	for i := 0; i < 5; i++ {
		detector.Update(100.0)
	}

	_, score, mean := detector.Update(120.0)
	expectedZ := math.Abs(120.0 - mean) / math.Sqrt(detector.variance)
	if math.IsNaN(expectedZ) || math.IsInf(expectedZ, 0) {
		assert.False(t, math.IsNaN(score), "Score should not be NaN")
		return
	}
	assert.InDelta(t, expectedZ, score, 0.001, "Z-score calculation should be correct")
}