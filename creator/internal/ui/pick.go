package ui

import (
	"fmt"
	"os/exec"
	"strings"
)

func pickFile(title, kind string) (string, error) {
	title = strings.TrimSpace(title)
	if title == "" {
		title = "Choose a file"
	}
	filterName, filterGlob := "All files", "*"
	switch kind {
	case "zip":
		filterName, filterGlob = "Retailer pack", "*.zip"
	case "iso":
		filterName, filterGlob = "Disk image", "*.iso *.img"
	}
	if p, err := exec.LookPath("zenity"); err == nil {
		cmd := exec.Command(p, "--file-selection", "--title="+title,
			"--file-filter="+filterName+" | "+filterGlob,
			"--file-filter=All files | *")
		out, err := cmd.Output()
		if err != nil {
			if ee, ok := err.(*exec.ExitError); ok && ee.ExitCode() == 1 {
				return "", fmt.Errorf("cancelled")
			}
			return "", fmt.Errorf("file picker: %w", err)
		}
		path := strings.TrimSpace(string(out))
		if path == "" {
			return "", fmt.Errorf("cancelled")
		}
		return path, nil
	}
	if p, err := exec.LookPath("kdialog"); err == nil {
		cmd := exec.Command(p, "--getopenfilename", ".", filterGlob)
		out, err := cmd.Output()
		if err != nil {
			return "", fmt.Errorf("cancelled")
		}
		path := strings.TrimSpace(string(out))
		if path == "" {
			return "", fmt.Errorf("cancelled")
		}
		return path, nil
	}
	if p, err := exec.LookPath("yad"); err == nil {
		cmd := exec.Command(p, "--file", "--title="+title)
		out, err := cmd.Output()
		if err != nil {
			return "", fmt.Errorf("cancelled")
		}
		path := strings.TrimSpace(string(out))
		if path == "" {
			return "", fmt.Errorf("cancelled")
		}
		return path, nil
	}
	return "", fmt.Errorf("no file picker (install zenity or kdialog), or type a path")
}
