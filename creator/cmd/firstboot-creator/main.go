package main

import (
	"context"
	"flag"
	"fmt"
	"io"
	"os"
	"strings"

	"github.com/Leon2332/First-Boot-Linux/creator/internal/assets"
	"github.com/Leon2332/First-Boot-Linux/creator/internal/cache"
	"github.com/Leon2332/First-Boot-Linux/creator/internal/catalog"
	"github.com/Leon2332/First-Boot-Linux/creator/internal/compose"
	"github.com/Leon2332/First-Boot-Linux/creator/internal/seedpath"
	"github.com/Leon2332/First-Boot-Linux/creator/internal/ui"
)

func main() {
	if len(os.Args) > 1 {
		switch os.Args[1] {
		case "compose":
			os.Exit(runCompose(os.Args[2:]))
		case "estimate":
			os.Exit(runEstimate(os.Args[2:]))
		case "help", "-h", "--help":
			usage(os.Stdout)
			return
		}
	}
	if err := ui.Run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func usage(w io.Writer) {
	fmt.Fprint(w, `First Boot shop USB creator

  firstboot-creator                 open the shop GUI
  firstboot-creator compose [opts]  write a disk image (no window)
  firstboot-creator estimate [opts] print stick / PC size

compose / estimate options:
  --name NAME
  --support TEXT
  --stage spec,spec      desktops to stage (distro:edition; bare distro = its default)
  --seed DIR             First Boot seed (default: build/seed)
  --out FILE             disk image (compose only)
  --cache DIR            ISO cache (default: ~/.cache/firstboot/images)
  --wallpaper-dark FILE
  --wallpaper-light FILE
  --password-file FILE   live-user password; "-" reads stdin
                         or set FIRSTBOOT_LIVE_PASSWORD
`)
}

func runEstimate(args []string) int {
	fs := flag.NewFlagSet("estimate", flag.ContinueOnError)
	stage := fs.String("stage", "", "")
	seedDir := fs.String("seed", "", "")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	off, seed, shop, err := prepare(*seedDir, *stage)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	_ = off
	est := compose.Plan(seed, shop)
	fmt.Println(est.Summary)
	fmt.Printf("image %s  stick %d GB  pc %d GB\n", est.NeedHuman, est.StickGB, est.DiskGB)
	return 0
}

func runCompose(args []string) int {
	fs := flag.NewFlagSet("compose", flag.ContinueOnError)
	name := fs.String("name", "", "")
	support := fs.String("support", "", "")
	stage := fs.String("stage", "", "")
	seedDir := fs.String("seed", "", "")
	out := fs.String("out", "", "")
	cacheDir := fs.String("cache", "", "")
	dark := fs.String("wallpaper-dark", "", "")
	light := fs.String("wallpaper-light", "", "")
	pwFile := fs.String("password-file", "", "")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	if *name == "" || *support == "" || *out == "" {
		fmt.Fprintln(os.Stderr, "compose needs --name, --support, and --out")
		return 2
	}
	off, seed, shop, err := prepare(*seedDir, *stage)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	if *dark == "" {
		*dark, err = assets.DefaultWallpaper("dark")
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
	}
	if *light == "" {
		*light, err = assets.DefaultWallpaper("light")
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
	}
	password, err := readPassword(*pwFile)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	r := catalog.Retailer{Name: *name, Support: *support, WallpaperDark: *dark, WallpaperLight: *light}
	if err := catalog.ValidateRetailer(r); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	store := cache.New(*cacheDir)
	err = compose.Write(context.Background(), compose.Request{
		Retailer: r,
		Shop:     shop,
		Official: off,
		Seed:     seed,
		Cache:    store,
		Out:      *out,
		Password: password,
		Progress: func(stage string, got, total int64) {
			if total > 0 {
				fmt.Fprintf(os.Stderr, "\r%s  %d%%   ", stage, got*100/total)
			} else {
				fmt.Fprintf(os.Stderr, "\r%s          ", stage)
			}
		},
	})
	fmt.Fprintln(os.Stderr)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	fmt.Println(*out)
	return 0
}

func prepare(seedDir, stage string) (*catalog.Official, *seedpath.Seed, *catalog.Shop, error) {
	off, err := catalog.LoadOfficial("")
	if err != nil {
		return nil, nil, nil, err
	}
	seed, err := seedpath.Locate(seedDir)
	if err != nil {
		return nil, nil, nil, err
	}
	var ids []string
	for _, p := range strings.Split(stage, ",") {
		p = strings.TrimSpace(p)
		if p != "" {
			ids = append(ids, p)
		}
	}
	shop, err := catalog.BuildShop(off, ids)
	if err != nil {
		return nil, nil, nil, err
	}
	return off, seed, shop, nil
}

func readPassword(path string) (string, error) {
	if env := os.Getenv("FIRSTBOOT_LIVE_PASSWORD"); env != "" {
		return env, nil
	}
	if path == "" {
		return "", nil
	}
	var raw []byte
	var err error
	if path == "-" {
		raw, err = io.ReadAll(os.Stdin)
	} else {
		raw, err = os.ReadFile(path)
	}
	if err != nil {
		return "", err
	}
	return strings.TrimRight(string(raw), "\n\r"), nil
}
