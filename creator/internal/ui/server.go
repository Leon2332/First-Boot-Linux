package ui

import (
	"bufio"
	"context"
	"embed"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/Leon2332/First-Boot-Linux/creator/internal/assets"
	"github.com/Leon2332/First-Boot-Linux/creator/internal/cache"
	"github.com/Leon2332/First-Boot-Linux/creator/internal/catalog"
	"github.com/Leon2332/First-Boot-Linux/creator/internal/compose"
	"github.com/Leon2332/First-Boot-Linux/creator/internal/devices"
	"github.com/Leon2332/First-Boot-Linux/creator/internal/seedpath"
)

//go:embed web/*
var webFS embed.FS

type session struct {
	off     *catalog.Official
	seed    *seedpath.Seed
	seedErr error
	dark    string
	light   string
	mu      sync.Mutex
	busy    bool
	stage   string
	got     int64
	total   int64
	done    bool
	jobErr  string
	tasks   []jobTask
	cancel  context.CancelFunc
}

func Run() error {
	if os.Geteuid() == 0 {
		return fmt.Errorf("do not run the shop GUI as root; writing a USB will ask for permission")
	}
	off, err := catalog.LoadOfficial("")
	if err != nil {
		return err
	}
	seed, seedErr := seedpath.Locate("")
	dark, _ := assets.DefaultWallpaper("dark")
	light, _ := assets.DefaultWallpaper("light")
	s := &session{off: off, seed: seed, seedErr: seedErr, dark: dark, light: light}

	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return err
	}
	url := "http://" + ln.Addr().String() + "/"
	fmt.Println("Shop USB creator:", url)
	go openBrowser(url)

	mux := http.NewServeMux()
	static, err := fs.Sub(webFS, "web")
	if err != nil {
		return err
	}
	mux.Handle("/", http.FileServer(http.FS(static)))
	mux.HandleFunc("/api/state", s.state)
	mux.HandleFunc("/api/estimate", s.estimate)
	mux.HandleFunc("/api/devices", s.listDevices)
	mux.HandleFunc("/api/wallpaper", s.uploadWallpaper)
	mux.HandleFunc("/api/wallpaper/reset", s.resetWallpaper)
	mux.HandleFunc("/api/wallpaper/dark", s.serveWallpaper("dark"))
	mux.HandleFunc("/api/wallpaper/light", s.serveWallpaper("light"))
	mux.HandleFunc("/api/logo/", s.logo)
	mux.HandleFunc("/api/icon", s.icon)
	mux.HandleFunc("/api/start", s.start)
	mux.HandleFunc("/api/cancel", s.cancelJob)
	mux.HandleFunc("/api/progress", s.progress)

	srv := &http.Server{Handler: mux, ReadHeaderTimeout: 10 * time.Second}
	return srv.Serve(ln)
}

func (s *session) state(w http.ResponseWriter, r *http.Request) {
	type distro struct {
		ID               string `json:"id"`
		Name             string `json:"name"`
		Version          string `json:"version"`
		Tagline          string `json:"tagline"`
		Description      string `json:"description"`
		Stageable        bool   `json:"stageable"`
		Redistributable  bool   `json:"redistributable"`
		SuggestedDefault bool   `json:"suggested_default"`
		Edition          string `json:"edition"`
		Size             string `json:"size"`
		Logo             bool   `json:"logo"`
	}
	var list []distro
	for _, d := range s.off.Distros {
		item := distro{
			ID: d.ID, Name: d.Name, Version: d.Version,
			Tagline: d.Tagline, Description: d.Description,
			Stageable: d.Stageable(), Redistributable: d.Redistributable,
			SuggestedDefault: d.SuggestedDefault,
			Logo:             assets.DistroLogo(d.ID) != "",
		}
		if ed := d.DefaultEdition(); ed != nil {
			item.Edition = ed.Name
			if ed.SizeBytes != nil {
				item.Size = catalog.FormatBytes(*ed.SizeBytes)
			}
		}
		list = append(list, item)
	}
	seedOK := s.seed != nil
	seedErr := ""
	if s.seedErr != nil {
		seedErr = s.seedErr.Error()
	}
	writeJSON(w, map[string]any{
		"distros":       list,
		"seed_ok":       seedOK,
		"seed_error":    seedErr,
		"default_image": defaultImagePath(),
	})
}

func (s *session) estimate(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Staged []string `json:"staged"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		httpError(w, 400, err)
		return
	}
	if s.seed == nil {
		httpError(w, 400, s.seedErr)
		return
	}
	shop, err := catalog.BuildShop(s.off, req.Staged)
	if err != nil {
		httpError(w, 400, err)
		return
	}
	est := compose.Plan(s.seed, shop)
	var names []string
	for _, d := range shop.Recommended {
		names = append(names, d.Name+" "+d.Version)
	}
	writeJSON(w, map[string]any{
		"summary":  est.Summary,
		"hint":     "On this stick: " + strings.Join(names, ", ") + ".",
		"stick_gb": est.StickGB,
		"disk_gb":  est.DiskGB,
	})
}

func (s *session) listDevices(w http.ResponseWriter, r *http.Request) {
	list, err := devices.List()
	if err != nil {
		httpError(w, 500, err)
		return
	}
	type disk struct {
		Path   string `json:"path"`
		Label  string `json:"label"`
		Size   int64  `json:"size"`
		System bool   `json:"system"`
		USB    bool   `json:"usb"`
	}
	out := make([]disk, 0, len(list))
	for _, d := range list {
		out = append(out, disk{Path: d.Path, Label: d.Label(), Size: d.Size, System: d.System, USB: d.USB})
	}
	writeJSON(w, map[string]any{"disks": out})
}

func (s *session) uploadWallpaper(w http.ResponseWriter, r *http.Request) {
	if err := r.ParseMultipartForm(20 << 20); err != nil {
		httpError(w, 400, err)
		return
	}
	which := r.FormValue("which")
	if which != "dark" && which != "light" {
		httpError(w, 400, fmt.Errorf("which must be dark or light"))
		return
	}
	f, hdr, err := r.FormFile("file")
	if err != nil {
		httpError(w, 400, err)
		return
	}
	defer f.Close()
	ext := strings.ToLower(filepath.Ext(hdr.Filename))
	if ext != ".jpg" && ext != ".jpeg" && ext != ".png" && ext != ".webp" {
		httpError(w, 400, fmt.Errorf("use a JPEG, PNG, or WebP"))
		return
	}
	dir, err := os.MkdirTemp("", "firstboot-wall-")
	if err != nil {
		httpError(w, 500, err)
		return
	}
	dest := filepath.Join(dir, which+ext)
	out, err := os.Create(dest)
	if err != nil {
		httpError(w, 500, err)
		return
	}
	if _, err := io.Copy(out, f); err != nil {
		out.Close()
		httpError(w, 500, err)
		return
	}
	out.Close()
	s.mu.Lock()
	if which == "dark" {
		s.dark = dest
	} else {
		s.light = dest
	}
	s.mu.Unlock()
	writeJSON(w, map[string]any{"ok": true})
}

func (s *session) resetWallpaper(w http.ResponseWriter, r *http.Request) {
	dark, _ := assets.DefaultWallpaper("dark")
	light, _ := assets.DefaultWallpaper("light")
	s.mu.Lock()
	s.dark, s.light = dark, light
	s.mu.Unlock()
	writeJSON(w, map[string]any{"ok": true})
}

func (s *session) serveWallpaper(which string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		s.mu.Lock()
		path := s.dark
		if which == "light" {
			path = s.light
		}
		s.mu.Unlock()
		if path == "" {
			http.NotFound(w, r)
			return
		}
		http.ServeFile(w, r, path)
	}
}

func (s *session) logo(w http.ResponseWriter, r *http.Request) {
	id := strings.TrimPrefix(r.URL.Path, "/api/logo/")
	p := assets.DistroLogo(id)
	if p == "" {
		http.NotFound(w, r)
		return
	}
	http.ServeFile(w, r, p)
}

func (s *session) icon(w http.ResponseWriter, r *http.Request) {
	p := assets.AppIcon()
	if p == "" {
		http.NotFound(w, r)
		return
	}
	http.ServeFile(w, r, p)
}

type startReq struct {
	Name          string   `json:"name"`
	Support       string   `json:"support"`
	Password      string   `json:"password"`
	EmptyPassword bool     `json:"empty_password"`
	Staged        []string `json:"staged"`
	Target        string   `json:"target"`
	Image         string   `json:"image"`
	Device        string   `json:"device"`
}

func (s *session) start(w http.ResponseWriter, r *http.Request) {
	var req startReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		httpError(w, 400, err)
		return
	}
	s.mu.Lock()
	if s.busy {
		s.mu.Unlock()
		httpError(w, 409, fmt.Errorf("already writing"))
		return
	}
	if s.seed == nil {
		err := s.seedErr
		s.mu.Unlock()
		httpError(w, 400, err)
		return
	}
	retailer := catalog.Retailer{
		Name: req.Name, Support: req.Support,
		WallpaperDark: s.dark, WallpaperLight: s.light,
	}
	s.busy = true
	s.done = false
	s.jobErr = ""
	s.stage = "Starting…"
	s.got, s.total = 0, 0
	s.tasks = nil
	seed := s.seed
	off := s.off
	s.mu.Unlock()

	if err := catalog.ValidateRetailer(retailer); err != nil {
		s.fail(err)
		httpError(w, 400, err)
		return
	}
	shop, err := catalog.BuildShop(off, req.Staged)
	if err != nil {
		s.fail(err)
		httpError(w, 400, err)
		return
	}
	if req.Image == "" {
		req.Image = defaultImagePath()
	}
	if req.Target == "usb" && req.Device == "" {
		err := fmt.Errorf("choose a USB stick")
		s.fail(err)
		httpError(w, 400, err)
		return
	}
	password := req.Password
	if req.EmptyPassword {
		password = ""
	}
	ctx, cancel := context.WithCancel(context.Background())
	s.mu.Lock()
	s.tasks = planTasks(shop, req.Device)
	s.cancel = cancel
	s.mu.Unlock()
	go s.run(ctx, seed, off, shop, retailer, password, req.Image, req.Device)
	writeJSON(w, map[string]any{"ok": true})
}

func (s *session) cancelJob(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	s.mu.Lock()
	cancel := s.cancel
	s.mu.Unlock()
	if cancel != nil {
		cancel()
	}
	writeJSON(w, map[string]any{"ok": true})
}

func (s *session) setProgress(stage string, got, total int64) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.stage = stage
	s.got = got
	s.total = total
	applyTaskProgress(s.tasks, stage)
}

func (s *session) run(ctx context.Context, seed *seedpath.Seed, off *catalog.Official, shop *catalog.Shop, retailer catalog.Retailer, password, image, device string) {
	err := compose.Write(ctx, compose.Request{
		Retailer: retailer,
		Shop:     shop,
		Official: off,
		Seed:     seed,
		Cache:    cache.New(assets.CacheDir()),
		Out:      image,
		Password: password,
		Progress: s.setProgress,
	})
	if err == nil && device != "" {
		s.setProgress("Waiting for permission…", 0, 0)
		err = writeStick(ctx, image, device, s.setProgress)
	}
	s.mu.Lock()
	s.busy = false
	s.done = true
	s.cancel = nil
	if errors.Is(err, context.Canceled) {
		s.jobErr = ""
		s.stage = "Cancelled."
		markActiveError(s.tasks)
	} else if err != nil {
		s.jobErr = err.Error()
		s.stage = "Stopped."
		markActiveError(s.tasks)
	} else if device != "" {
		s.stage = "Done. You can boot PCs from that stick."
		s.got, s.total = 1, 1
		applyTaskProgress(s.tasks, s.stage)
	} else {
		s.stage = "Done. Disk image saved to " + image
		s.got, s.total = 1, 1
		applyTaskProgress(s.tasks, s.stage)
	}
	s.mu.Unlock()
}

func (s *session) fail(err error) {
	s.mu.Lock()
	s.busy = false
	s.done = true
	if err != nil {
		s.jobErr = err.Error()
	}
	markActiveError(s.tasks)
	s.mu.Unlock()
}

func (s *session) progress(w http.ResponseWriter, r *http.Request) {
	s.mu.Lock()
	defer s.mu.Unlock()
	frac := 0.0
	if s.total > 0 {
		frac = float64(s.got) / float64(s.total)
	}
	tasks := append([]jobTask(nil), s.tasks...)
	writeJSON(w, map[string]any{
		"stage":    s.stage,
		"fraction": frac,
		"done":     s.done,
		"error":    s.jobErr,
		"tasks":    tasks,
	})
}

func writeStick(ctx context.Context, image, device string, progress func(string, int64, int64)) error {
	helper, err := materializeHelper()
	if err != nil {
		return err
	}
	var cmd *exec.Cmd
	if p, err := exec.LookPath("pkexec"); err == nil {
		cmd = exec.Command(p, helper, "--image", image, "--device", device)
	} else if p, err := exec.LookPath("sudo"); err == nil {
		cmd = exec.Command(p, helper, "--image", image, "--device", device)
	} else {
		return fmt.Errorf("need pkexec or sudo to write %s", device)
	}
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return err
	}
	if err := cmd.Start(); err != nil {
		return fmt.Errorf("write USB: %w", err)
	}
	stop := make(chan struct{})
	defer close(stop)
	go func() {
		select {
		case <-ctx.Done():
			if cmd.Process != nil {
				_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGTERM)
				time.Sleep(300 * time.Millisecond)
				_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
			}
		case <-stop:
		}
	}()
	sc := bufio.NewScanner(stderr)
	var errBuf strings.Builder
	for sc.Scan() {
		line := sc.Text()
		if got, total, ok := parseWriteProgress(line); ok {
			if progress != nil {
				progress("Writing to disk", got, total)
			}
			continue
		}
		if strings.TrimSpace(line) != "" {
			errBuf.WriteString(line)
			errBuf.WriteByte('\n')
		}
	}
	if err := cmd.Wait(); err != nil {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		msg := strings.TrimSpace(errBuf.String())
		if msg != "" {
			return fmt.Errorf("write USB: %w\n%s", err, msg)
		}
		return fmt.Errorf("write USB: %w", err)
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	return nil
}

func defaultImagePath() string {
	if repo, err := assets.RepoRoot(""); err == nil {
		return filepath.Join(repo, "build", "fbl-creator.img")
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return "firstboot-usb.img"
	}
	return filepath.Join(home, "firstboot-usb.img")
}

func openBrowser(url string) {
	for _, c := range [][]string{
		{"xdg-open", url},
		{"gio", "open", url},
	} {
		if _, err := exec.LookPath(c[0]); err == nil {
			_ = exec.Command(c[0], c[1:]...).Start()
			return
		}
	}
}

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(v)
}

func httpError(w http.ResponseWriter, code int, err error) {
	if err == nil {
		http.Error(w, `{"error":"error"}`, code)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": err.Error()})
}
