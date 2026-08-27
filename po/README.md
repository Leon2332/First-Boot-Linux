# Translations

English is the source. Translators work on **Hosted Weblate** (hosted.weblate.org), not by editing these files by hand as the workflow.

The live chooser lists only languages we ship here. English is always present. Add a row to `languages.json` and a `xx.po` only when that language is ready to ship. Distro and desktop **names** stay untranslated (Ubuntu, Cinnamon). Taglines and descriptions are translated.

Afrikaans negation: do not add a trailing *nie* after *geen* (“Geen netwerke gevind”). Use *nie … nie* only for ordinary verbal negation (“Die blaaier is nie op hierdie beeld nie”).

## Files

| File | Role |
| --- | --- |
| `firstboot.pot` | Gettext template, extracted from the chooser |
| `af.po` | Afrikaans (first translation) |
| `languages.json` | Shipped languages: id, native name, English name |
| `LINGUAS` | Gettext language list (not including English) |

Domain: `firstboot`. Runtime looks for `po/*.po` in this tree, or `/usr/share/firstboot/locale/<lang>/LC_MESSAGES/firstboot.po` on the live image.

## Hosted Weblate

Create a project on [hosted.weblate.org](https://hosted.weblate.org/) pointing at this git repository.

Component settings:

- File format: GNU gettext
- File mask: `po/*.po`
- Monolingual base / template: `po/firstboot.pot`
- New language: `po/%(code)s.po`
- Source language: `en`

After Weblate merges a complete language, add it to `languages.json` and `LINGUAS` so the chooser and USB Creator offer it. Do not copy the long mockup list into the kiosk.

Refresh the template from the chooser tree:

```bash
xgettext --language=Python --from-code=UTF-8 --keyword=_ \
  --package-name=firstboot --msgid-bugs-address= \
  -o po/firstboot.pot chooser/firstboot/*.py chooser/firstboot/osinstall/*.py
```

Then `msgmerge --update po/af.po po/firstboot.pot`.
