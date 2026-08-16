package ui

import (
	"fmt"
	"path/filepath"
	"strings"

	"github.com/Leon2332/First-Boot-Linux/creator/internal/catalog"
)

type jobTask struct {
	ID     string `json:"id"`
	Label  string `json:"label"`
	Status string `json:"status"`
}

func planTasks(shop *catalog.Shop, device string) []jobTask {
	var tasks []jobTask
	if shop != nil {
		for _, d := range shop.Recommended {
			for _, e := range d.Editions {
				if !e.Local {
					continue
				}
				name := filepath.Base(e.File)
				if name == "" || name == "." {
					continue
				}
				tasks = append(tasks, jobTask{
					ID:     "download:" + name,
					Label:  downloadLabel(d, e),
					Status: "pending",
				})
			}
		}
	}
	tasks = append(tasks, jobTask{ID: "build", Label: "Building disk image", Status: "pending"})
	if device != "" {
		tasks = append(tasks, jobTask{ID: "write", Label: "Writing to disk", Status: "pending"})
	}
	return tasks
}

func downloadLabel(d catalog.ShopDistro, e catalog.ShopEdition) string {
	parts := []string{d.Name, d.Version, e.Name}
	var keep []string
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p != "" {
			keep = append(keep, p)
		}
	}
	if len(keep) == 0 {
		return "Downloading image"
	}
	return "Downloading " + strings.Join(keep, " ")
}

func taskIDForStage(stage string) string {
	switch {
	case strings.HasPrefix(stage, "download "):
		return "download:" + strings.TrimPrefix(stage, "download ")
	case stage == "Waiting for permission…" || stage == "Writing to disk":
		return "write"
	case strings.HasPrefix(stage, "Done."):
		return ""
	case stage == "done":
		return "build"
	case stage == "Starting…" || stage == "Stopped.":
		return ""
	default:
		return "build"
	}
}

func applyTaskProgress(tasks []jobTask, stage string) {
	if stage == "done" {
		for i := range tasks {
			if tasks[i].ID != "write" {
				tasks[i].Status = "done"
			}
		}
		return
	}
	id := taskIDForStage(stage)
	if id == "" {
		if strings.HasPrefix(stage, "Done.") {
			for i := range tasks {
				tasks[i].Status = "done"
			}
		}
		return
	}
	idx := -1
	for i := range tasks {
		if tasks[i].ID == id {
			idx = i
			break
		}
	}
	if idx < 0 {
		return
	}
	for i := range tasks {
		switch {
		case i < idx:
			tasks[i].Status = "done"
		case i == idx:
			if tasks[i].Status != "done" {
				tasks[i].Status = "active"
			}
		default:
			if tasks[i].Status == "active" {
				tasks[i].Status = "pending"
			}
		}
	}
}

func markActiveError(tasks []jobTask) {
	for i := range tasks {
		if tasks[i].Status == "active" {
			tasks[i].Status = "error"
			return
		}
	}
}

func parseWriteProgress(line string) (got, total int64, ok bool) {
	line = strings.TrimSpace(line)
	if !strings.HasPrefix(line, "PROGRESS ") {
		return 0, 0, false
	}
	var g, t int64
	n, err := fmt.Sscanf(line, "PROGRESS %d %d", &g, &t)
	if err != nil || n != 2 || t <= 0 {
		return 0, 0, false
	}
	return g, t, true
}
