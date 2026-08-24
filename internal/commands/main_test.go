package commands

import (
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

// TestMain provides the external bd prerequisite for every commands-package
// test. Individual tests that care about exact bd output prepend their own
// stub. This keeps the remaining passthrough tests independent of whatever an
// operator or hosted runner happens to have installed.
func TestMain(m *testing.M) {
	binDir, err := os.MkdirTemp("", "bdh-test-bin-")
	if err != nil {
		fmt.Fprintf(os.Stderr, "create test bin directory: %v\n", err)
		os.Exit(1)
	}
	name := "bd"
	content := []byte("#!/bin/sh\nprintf '%s\\n' \"$@\"\n")
	if runtime.GOOS == "windows" {
		name = "bd.cmd"
		content = []byte("@echo off\r\necho %*\r\nexit /b 0\r\n")
	}
	if err := os.WriteFile(filepath.Join(binDir, name), content, 0755); err != nil {
		fmt.Fprintf(os.Stderr, "write test bd stub: %v\n", err)
		os.Exit(1)
	}
	if err := os.Setenv("PATH", binDir+string(os.PathListSeparator)+os.Getenv("PATH")); err != nil {
		fmt.Fprintf(os.Stderr, "set test PATH: %v\n", err)
		os.Exit(1)
	}
	// Tests must never inherit a developer's live BeadHub endpoint, key, or
	// selected account. Tests that exercise environment precedence replace
	// these isolated defaults with t.Setenv.
	for name, value := range map[string]string{
		"AW_CONFIG_PATH":  "",
		"BEADHUB_API_KEY": "",
		"BEADHUB_URL":     "",
		"HOME":            binDir,
	} {
		if err := os.Setenv(name, value); err != nil {
			fmt.Fprintf(os.Stderr, "set test %s: %v\n", name, err)
			os.Exit(1)
		}
	}

	code := m.Run()
	if err := os.RemoveAll(binDir); err != nil {
		fmt.Fprintf(os.Stderr, "remove test bin directory: %v\n", err)
		if code == 0 {
			code = 1
		}
	}
	os.Exit(code)
}
