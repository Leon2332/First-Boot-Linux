package ui

import (
	"bufio"
	"bytes"
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
	"github.com/Leon2332/First-Boot-Linux/creator/internal/i18n"
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
	packs   []*catalog.Pack
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
	mux.HandleFunc("/api/ui-language", s.setUILanguage)
	mux.HandleFunc("/api/estimate", s.estimate)
	mux.HandleFunc("/api/devices", s.listDevices)
	mux.HandleFunc("/api/wallpaper", s.uploadWallpaper)
	mux.HandleFunc("/api/wallpaper/reset", s.resetWallpaper)
	mux.HandleFunc("/api/wallpaper/dark", s.serveWallpaper("dark"))
	mux.HandleFunc("/api/wallpaper/light", s.serveWallpaper("light"))
	mux.HandleFunc("/api/logo/", s.logo)
	mux.HandleFunc("/api/icon", s.icon)
	mux.HandleFunc("/api/pick-file", s.pickFile)
	mux.HandleFunc("/api/custom-pack", s.addPack)
	mux.HandleFunc("/api/custom-pack-upload", s.uploadPack)
	mux.HandleFunc("/api/custom-iso", s.attachISO)
	mux.HandleFunc("POST /api/custom-remove", s.removePack)
	mux.HandleFunc("/api/custom-remove", s.removePack)
	mux.HandleFunc("/api/start", s.start)
	mux.HandleFunc("/api/cancel", s.cancelJob)
	mux.HandleFunc("/api/progress", s.progress)

	srv := &http.Server{Handler: mux, ReadHeaderTimeout: 10 * time.Second}
	return srv.Serve(ln)
}

func (s *session) state(w http.ResponseWriter, r *http.Request) {
	type edition struct {
		ID        string `json:"id"`
		Name      string `json:"name"`
		Size      string `json:"size"`
		Stageable bool   `json:"stageable"`
		NeedISO   bool   `json:"need_iso"`
	}
	type distro struct {
		ID          string    `json:"id"`
		Name        string    `json:"name"`
		Version     string    `json:"version"`
		Tagline     string    `json:"tagline"`
		Description string    `json:"description"`
		Stageable   bool      `json:"stageable"`
		Logo        bool      `json:"logo"`
		Custom      bool      `json:"custom"`
		SecureBoot  bool      `json:"secure_boot"`
		Editions    []edition `json:"editions"`
	}
	var list []distro
	s.mu.Lock()
	packs := append([]*catalog.Pack(nil), s.packs...)
	s.mu.Unlock()
	for _, d := range s.off.Distros {
		if !d.Offerable() {
			continue
		}
		item := distro{
			ID: d.ID, Name: d.Name, Version: d.Version,
			Tagline: d.Tagline, Description: d.Description,
			Stageable:  d.Stageable(),
			Logo:       assets.DistroLogo(d.ID) != "",
			SecureBoot: d.SecureBoot,
		}
		for _, ed := range d.Editions {
			if !ed.Pinned() {
				continue
			}
			row := edition{
				ID: ed.ID, Name: ed.Name,
				Stageable: d.CanStageEdition(ed),
			}
			if ed.SizeBytes != nil {
				row.Size = catalog.FormatBytes(*ed.SizeBytes)
			}
			item.Editions = append(item.Editions, row)
		}
		if len(item.Editions) == 0 {
			continue
		}
		list = append(list, item)
	}
	for _, p := range packs {
		if p == nil {
			continue
		}
		item := distro{
			ID: p.ID, Name: p.Name, Version: p.Version,
			Tagline: p.Tagline, Description: p.Description,
			Logo:       p.LogoPath != "" && assets.FileExists(p.LogoPath),
			Custom:     true,
			SecureBoot: p.SecureBoot,
		}
		anyISO := false
		for _, ed := range p.Editions {
			row := edition{
				ID: ed.ID, Name: ed.Name,
				Stageable: p.CanStageEdition(ed),
				NeedISO:   !p.CanStageEdition(ed),
			}
			if ed.SizeBytes > 0 {
				row.Size = catalog.FormatBytes(ed.SizeBytes)
			}
			if row.Stageable {
				anyISO = true
			}
			item.Editions = append(item.Editions, row)
		}
		item.Stageable = anyISO
		list = append(list, item)
	}
	seedOK := s.seed != nil
	seedErr := ""
	if s.seedErr != nil {
		seedErr = s.seedErr.Error()
	}
	langs, _ := catalog.LoadLanguages("")
	boards, _ := catalog.LoadKeyboards("")
	uiLang := i18n.Load()
	writeJSON(w, map[string]any{
		"distros":       list,
		"languages":     i18n.Supported(langs),
		"keyboards":     boards,
		"ui_language":   uiLang,
		"catalog":       i18n.CatalogWithPacks(uiLang, packs),
		"seed_ok":       seedOK,
		"seed_error":    seedErr,
		"default_image": defaultImagePath(),
	})
}

func (s *session) setUILanguage(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var req struct {
		Language string `json:"language"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		httpError(w, 400, err)
		return
	}
	lid, err := i18n.Save(req.Language)
	if err != nil {
		httpError(w, 500, err)
		return
	}
	s.mu.Lock()
	packs := append([]*catalog.Pack(nil), s.packs...)
	s.mu.Unlock()
	writeJSON(w, map[string]any{
		"language": lid,
		"catalog":  i18n.CatalogWithPacks(lid, packs),
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
	s.mu.Lock()
	packs := append([]*catalog.Pack(nil), s.packs...)
	s.mu.Unlock()
	shop, err := catalog.BuildShop(s.off, req.Staged, packs...)
	if err != nil {
		httpError(w, 400, err)
		return
	}
	est := compose.Plan(s.seed, shop)
	var names []string
	for _, d := range shop.Recommended {
		for _, e := range d.Editions {
			if e.Local {
				names = append(names, strings.TrimSpace(d.Name+" "+e.Name))
			}
		}
	}
	writeJSON(w, map[string]any{
		"summary":  est.Summary,
		"hint":     "On this stick: " + strings.Join(names, ", ") + ".",
		"stick_gb": est.StickGB,
		"disk_gb":  est.DiskGB,
		"need":     est.NeedHuman,
		"names":    names,
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
	s.mu.Lock()
	for _, p := range s.packs {
		if p != nil && p.ID == id && p.LogoPath != "" && assets.FileExists(p.LogoPath) {
			path := p.LogoPath
			s.mu.Unlock()
			http.ServeFile(w, r, path)
			return
		}
	}
	s.mu.Unlock()
	p := assets.DistroLogo(id)
	if p == "" {
		http.NotFound(w, r)
		return
	}
	http.ServeFile(w, r, p)
}

func (s *session) pickFile(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var req struct {
		Kind  string `json:"kind"`
		Title string `json:"title"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		httpError(w, 400, err)
		return
	}
	path, err := pickFile(req.Title, req.Kind)
	if err != nil {
		httpError(w, 400, err)
		return
	}
	writeJSON(w, map[string]any{"path": path})
}

func (s *session) addPack(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var req struct {
		Path string `json:"path"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		httpError(w, 400, err)
		return
	}
	if err := s.loadPack(req.Path); err != nil {
		httpError(w, 400, err)
		return
	}
	writeJSON(w, map[string]any{"ok": true})
}

func (s *session) uploadPack(w http.ResponseWriter, r *http.Request) {
	if err := r.ParseMultipartForm(32 << 20); err != nil {
		httpError(w, 400, err)
		return
	}
	f, hdr, err := r.FormFile("file")
	if err != nil {
		httpError(w, 400, err)
		return
	}
	defer f.Close()
	if strings.ToLower(filepath.Ext(hdr.Filename)) != ".zip" {
		httpError(w, 400, fmt.Errorf("use a .zip pack"))
		return
	}
	dir, err := os.MkdirTemp("", "firstboot-pack-")
	if err != nil {
		httpError(w, 500, err)
		return
	}
	dest := filepath.Join(dir, filepath.Base(hdr.Filename))
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
	if err := s.loadPack(dest); err != nil {
		httpError(w, 400, err)
		return
	}
	writeJSON(w, map[string]any{"ok": true})
}

func (s *session) loadPack(path string) error {
	path = strings.TrimSpace(path)
	if path == "" {
		return fmt.Errorf("choose a pack zip")
	}
	pack, err := catalog.LoadZip(path, catalog.PackCacheDir(), assets.CacheDir(), s.off)
	if err != nil {
		return err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]*catalog.Pack, 0, len(s.packs)+1)
	for _, p := range s.packs {
		if p != nil && p.ID != pack.ID {
			out = append(out, p)
		}
	}
	s.packs = append(out, pack)
	return nil
}

func (s *session) attachISO(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var req struct {
		ID      string `json:"id"`
		Edition string `json:"edition"`
		Path    string `json:"path"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		httpError(w, 400, err)
		return
	}
	s.mu.Lock()
	p := catalog.PackByID(s.packs, req.ID)
	if p == nil {
		s.mu.Unlock()
		httpError(w, 400, fmt.Errorf("unknown pack"))
		return
	}
	err := catalog.AttachISO(p, req.Edition, req.Path)
	var size int64
	if err == nil {
		if ed := p.Edition(req.Edition); ed != nil {
			size = ed.SizeBytes
		}
	}
	s.mu.Unlock()
	if err != nil {
		httpError(w, 400, err)
		return
	}
	writeJSON(w, map[string]any{"ok": true, "size": catalog.FormatBytes(size)})
}

func (s *session) removePack(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var req struct {
		ID string `json:"id"`
	}
	raw, _ := io.ReadAll(r.Body)
	if len(bytes.TrimSpace(raw)) > 0 {
		_ = json.Unmarshal(raw, &req)
	}
	id := strings.TrimSpace(req.ID)
	if id == "" {
		id = strings.TrimSpace(r.URL.Query().Get("id"))
	}
	if id == "" {
		httpError(w, 400, fmt.Errorf("missing pack id"))
		return
	}
	s.mu.Lock()
	out := make([]*catalog.Pack, 0, len(s.packs))
	for _, p := range s.packs {
		if p == nil {
			continue
		}
		if strings.EqualFold(strings.TrimSpace(p.ID), id) {
			continue
		}
		out = append(out, p)
	}
	remaining := make([]string, 0, len(out))
	for _, p := range out {
		remaining = append(remaining, p.ID)
	}
	s.packs = out
	s.mu.Unlock()
	writeJSON(w, map[string]any{"ok": true, "removed": id, "remaining": remaining})
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
	Language      string   `json:"language"`
	Keyboard      string   `json:"keyboard"`
	Timezone      string   `json:"timezone"`
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
	langs, _ := catalog.LoadLanguages("")
	boards, _ := catalog.LoadKeyboards("")
	retailer := catalog.Retailer{
		Name: req.Name, Support: req.Support,
		WallpaperDark: s.dark, WallpaperLight: s.light,
		Language: catalog.NormalizeRetailerLanguage(req.Language, langs),
		Keyboard: catalog.NormalizeRetailerKeyboard(req.Keyboard, boards),
		Timezone: catalog.NormalizeRetailerTimezone(req.Timezone),
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
	s.mu.Lock()
	packs := append([]*catalog.Pack(nil), s.packs...)
	s.mu.Unlock()
	shop, err := catalog.BuildShop(off, req.Staged, packs...)
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
	go s.run(ctx, seed, off, shop, packs, retailer, password, req.Image, req.Device)
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

func (s *session) run(ctx context.Context, seed *seedpath.Seed, off *catalog.Official, shop *catalog.Shop, packs []*catalog.Pack, retailer catalog.Retailer, password, image, device string) {
	err := compose.Write(ctx, compose.Request{
		Retailer: retailer,
		Shop:     shop,
		Official: off,
		Packs:    packs,
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
	w.Header().Set("Cache-Control", "no-store")
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
