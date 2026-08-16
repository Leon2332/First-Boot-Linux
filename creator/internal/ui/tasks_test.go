package ui

import (
	"testing"

	"github.com/Leon2332/First-Boot-Linux/creator/internal/catalog"
)

func testShop() *catalog.Shop {
	return &catalog.Shop{
		SchemaVersion: 1,
		Recommended: []catalog.ShopDistro{
			{
				Name:    "Ubuntu",
				Version: "26.04 LTS",
				Editions: []catalog.ShopEdition{
					{Name: "GNOME", Local: true, File: "images/ubuntu-26.04-desktop-amd64.iso"},
				},
			},
			{
				Name:    "Linux Mint",
				Version: "22.3",
				Editions: []catalog.ShopEdition{
					{Name: "Cinnamon", Local: true, File: "images/linuxmint-22.3-cinnamon-64bit.iso"},
				},
			},
		},
	}
}

func TestPlanTasksUSB(t *testing.T) {
	tasks := planTasks(testShop(), "/dev/sdb")
	if len(tasks) != 4 {
		t.Fatalf("got %d tasks: %+v", len(tasks), tasks)
	}
	want := []string{
		"download:ubuntu-26.04-desktop-amd64.iso",
		"download:linuxmint-22.3-cinnamon-64bit.iso",
		"build",
		"write",
	}
	labels := []string{
		"Downloading Ubuntu 26.04 LTS GNOME",
		"Downloading Linux Mint 22.3 Cinnamon",
		"Building disk image",
		"Writing to disk",
	}
	for i, id := range want {
		if tasks[i].ID != id || tasks[i].Label != labels[i] || tasks[i].Status != "pending" {
			t.Fatalf("task %d: %+v", i, tasks[i])
		}
	}
}

func TestPlanTasksImageOnly(t *testing.T) {
	tasks := planTasks(testShop(), "")
	if len(tasks) != 3 || tasks[2].ID != "build" {
		t.Fatalf("unexpected: %+v", tasks)
	}
}

func TestApplyTaskProgress(t *testing.T) {
	tasks := planTasks(testShop(), "/dev/sdb")
	applyTaskProgress(tasks, "download ubuntu-26.04-desktop-amd64.iso")
	if tasks[0].Status != "active" || tasks[1].Status != "pending" {
		t.Fatalf("first download: %+v", tasks)
	}
	applyTaskProgress(tasks, "download linuxmint-22.3-cinnamon-64bit.iso")
	if tasks[0].Status != "done" || tasks[1].Status != "active" {
		t.Fatalf("second download: %+v", tasks)
	}
	applyTaskProgress(tasks, "write FBL-DATA")
	if tasks[1].Status != "done" || tasks[2].Status != "active" || tasks[3].Status != "pending" {
		t.Fatalf("build: %+v", tasks)
	}
	applyTaskProgress(tasks, "done")
	if tasks[2].Status != "done" || tasks[3].Status != "pending" {
		t.Fatalf("compose done must not tick write: %+v", tasks)
	}
	applyTaskProgress(tasks, "Waiting for permission…")
	if tasks[2].Status != "done" || tasks[3].Status != "active" {
		t.Fatalf("permission: %+v", tasks)
	}
	applyTaskProgress(tasks, "Writing to disk")
	if tasks[3].Status != "active" {
		t.Fatalf("write: %+v", tasks)
	}
	applyTaskProgress(tasks, "Done. You can boot PCs from that stick.")
	for i, tk := range tasks {
		if tk.Status != "done" {
			t.Fatalf("task %d not done: %+v", i, tk)
		}
	}
}

func TestParseWriteProgress(t *testing.T) {
	g, tot, ok := parseWriteProgress("PROGRESS 512 1024")
	if !ok || g != 512 || tot != 1024 {
		t.Fatalf("got %d %d %v", g, tot, ok)
	}
	if _, _, ok := parseWriteProgress("write USB: denied"); ok {
		t.Fatal("non-progress line")
	}
}
