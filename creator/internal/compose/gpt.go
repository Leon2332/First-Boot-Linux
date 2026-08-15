package compose

import (
	"crypto/rand"
	"encoding/binary"
	"fmt"
	"hash/crc32"
	"os"
	"unicode/utf16"
)

const (
	sectorSize      = 512
	gptFirstUsable  = 2048
	gptHeaderSectors = 1
	gptEntryBytes    = 128
	gptEntries       = 128
	gptTableSectors  = (gptEntries * gptEntryBytes) / sectorSize
)

var (
	typeEFI   = mustGUID("C12A7328-F81F-11D2-BA4B-00A0C93EC93B")
	typeLinux = mustGUID("0FC63DAF-8483-4772-8E79-3D69D8477DE4")
)

type gptPart struct {
	Type  [16]byte
	GUID  [16]byte
	Start uint64
	End   uint64
	Name  string
}

func writeGPT(f *os.File, size int64, parts []gptPart) error {
	if size%sectorSize != 0 {
		return fmt.Errorf("image size must be a multiple of %d", sectorSize)
	}
	total := uint64(size / sectorSize)
	if total < gptFirstUsable+34+1 {
		return fmt.Errorf("image too small for GPT")
	}
	lastUsable := total - 34
	diskGUID := randomGUID()

	var table [gptEntries * gptEntryBytes]byte
	for i, p := range parts {
		if p.Start < gptFirstUsable || p.End > lastUsable || p.Start > p.End {
			return fmt.Errorf("partition %d has invalid range", i+1)
		}
		off := i * gptEntryBytes
		copy(table[off:off+16], p.Type[:])
		copy(table[off+16:off+32], p.GUID[:])
		binary.LittleEndian.PutUint64(table[off+32:], p.Start)
		binary.LittleEndian.PutUint64(table[off+40:], p.End)
		// flags stay zero
		name := utf16.Encode([]rune(p.Name))
		if len(name) > 36 {
			name = name[:36]
		}
		for j, r := range name {
			binary.LittleEndian.PutUint16(table[off+56+j*2:], r)
		}
	}
	entriesCRC := crc32.ChecksumIEEE(table[:])

	writeHeader := func(lba, alt, entriesLBA uint64) error {
		hdr := make([]byte, sectorSize)
		copy(hdr[0:8], []byte("EFI PART"))
		binary.LittleEndian.PutUint32(hdr[8:], 0x00010000)
		binary.LittleEndian.PutUint32(hdr[12:], 92)
		binary.LittleEndian.PutUint64(hdr[24:], lba)
		binary.LittleEndian.PutUint64(hdr[32:], alt)
		binary.LittleEndian.PutUint64(hdr[40:], gptFirstUsable)
		binary.LittleEndian.PutUint64(hdr[48:], lastUsable)
		copy(hdr[56:72], diskGUID[:])
		binary.LittleEndian.PutUint64(hdr[72:], entriesLBA)
		binary.LittleEndian.PutUint32(hdr[80:], gptEntries)
		binary.LittleEndian.PutUint32(hdr[84:], gptEntryBytes)
		binary.LittleEndian.PutUint32(hdr[88:], entriesCRC)
		crc := crc32.ChecksumIEEE(hdr[:92])
		binary.LittleEndian.PutUint32(hdr[16:], crc)
		if _, err := f.WriteAt(hdr, int64(lba)*sectorSize); err != nil {
			return err
		}
		return nil
	}

	if err := writeProtectiveMBR(f, total); err != nil {
		return err
	}
	primaryEntries := uint64(2)
	backupEntries := total - 33
	if err := writeHeader(1, total-1, primaryEntries); err != nil {
		return err
	}
	if _, err := f.WriteAt(table[:], int64(primaryEntries)*sectorSize); err != nil {
		return err
	}
	if _, err := f.WriteAt(table[:], int64(backupEntries)*sectorSize); err != nil {
		return err
	}
	if err := writeHeader(total-1, 1, backupEntries); err != nil {
		return err
	}
	return nil
}

func writeProtectiveMBR(f *os.File, total uint64) error {
	mbr := make([]byte, sectorSize)
	// One protective partition, type 0xEE, covering the disk.
	mbr[446] = 0x00
	mbr[447] = 0x00
	mbr[448] = 0x02
	mbr[449] = 0x00
	mbr[450] = 0xEE
	mbr[451] = 0xFF
	mbr[452] = 0xFF
	mbr[453] = 0xFF
	binary.LittleEndian.PutUint32(mbr[454:], 1)
	size := total - 1
	if size > 0xFFFFFFFF {
		size = 0xFFFFFFFF
	}
	binary.LittleEndian.PutUint32(mbr[458:], uint32(size))
	mbr[510] = 0x55
	mbr[511] = 0xAA
	_, err := f.WriteAt(mbr, 0)
	return err
}

func randomGUID() [16]byte {
	var g [16]byte
	_, _ = rand.Read(g[:])
	g[6] = (g[6] & 0x0f) | 0x40
	g[8] = (g[8] & 0x3f) | 0x80
	return mixedGUID(g)
}

func mustGUID(s string) [16]byte {
	g, err := parseGUID(s)
	if err != nil {
		panic(err)
	}
	return g
}

func parseGUID(s string) ([16]byte, error) {
	var hex [16]byte
	j := 0
	for i := 0; i < len(s); i++ {
		c := s[i]
		if c == '-' {
			continue
		}
		if j >= 32 {
			return [16]byte{}, fmt.Errorf("guid too long")
		}
		var v byte
		switch {
		case c >= '0' && c <= '9':
			v = c - '0'
		case c >= 'a' && c <= 'f':
			v = c - 'a' + 10
		case c >= 'A' && c <= 'F':
			v = c - 'A' + 10
		default:
			return [16]byte{}, fmt.Errorf("bad guid")
		}
		if j%2 == 0 {
			hex[j/2] = v << 4
		} else {
			hex[j/2] |= v
		}
		j++
	}
	if j != 32 {
		return [16]byte{}, fmt.Errorf("bad guid length")
	}
	return mixedGUID(hex), nil
}

// mixedGUID stores the first three UUID fields little-endian, as GPT does.
func mixedGUID(be [16]byte) [16]byte {
	var out [16]byte
	out[0], out[1], out[2], out[3] = be[3], be[2], be[1], be[0]
	out[4], out[5] = be[5], be[4]
	out[6], out[7] = be[7], be[6]
	copy(out[8:], be[8:])
	return out
}
