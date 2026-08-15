package compose

import (
	"bytes"
	"os"
	"testing"
)

func TestWriteGPT(t *testing.T) {
	const size = 8 << 20
	dir := t.TempDir()
	path := dir + "/disk.img"
	f, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := f.Truncate(size); err != nil {
		t.Fatal(err)
	}
	parts := []gptPart{
		{Type: typeEFI, GUID: randomGUID(), Start: 2048, End: 4095, Name: "FBL-ESP"},
		{Type: typeLinux, GUID: randomGUID(), Start: 4096, End: 8191, Name: "FBL-SYS"},
		{Type: typeLinux, GUID: randomGUID(), Start: 8192, End: uint64(size/512 - 34), Name: "FBL-DATA"},
	}
	if err := writeGPT(f, size, parts); err != nil {
		t.Fatal(err)
	}
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if raw[510] != 0x55 || raw[511] != 0xAA {
		t.Fatalf("missing protective MBR signature")
	}
	if raw[450] != 0xEE {
		t.Fatalf("protective partition type %02x", raw[450])
	}
	if !bytes.Equal(raw[512:520], []byte("EFI PART")) {
		t.Fatalf("missing primary GPT header")
	}
	last := size - 512
	if !bytes.Equal(raw[last:last+8], []byte("EFI PART")) {
		t.Fatalf("missing backup GPT header")
	}
	if !bytes.Contains(raw, []byte{'F', 0, 'B', 0, 'L', 0, '-', 0, 'E', 0, 'S', 0, 'P', 0}) {
		t.Fatalf("missing FBL-ESP name")
	}
}
