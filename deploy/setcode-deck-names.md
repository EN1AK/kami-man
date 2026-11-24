# Setcode deck naming

The default name is computed from the main deck's `datas.setcode` in the shared
Chinese card catalog. `strings.conf` supplies the Chinese labels. The bundled
`services/mycard_archive/setnames.conf` is a fallback for installations without
a shared label table (snapshot from Fluorohydride/ygopro commit
`128a5589411062a375b85a672e296d597bb10355`).

- Unpack the signed SQLite integer into four unsigned 16-bit setcodes.
- Merge each low-12-bit family and count each physical main card once per family.
- Keep a family only if at least three main-deck cards match.
- Use the parent label when parent/sibling fields occur; retain a sole child
  label. If no parent label exists, use the lowest observed named child.
- Exclude `融合`, `禁忌的`, and `欢聚友伴` to avoid common generic tags.
- Concatenate by ascending physical count, breaking ties by family code.
- Add `60` for a 60-card main deck. No matches produce `未识别`.
- Extra and side deck cards do not contribute.

The 100-player archived preview captured at 2026-10-20 19:33:32 +08:00 was
recomputed against this implementation: all 100 names matched the preview.
These names describe field evidence rather than manually confirmed archetypes;
long component names and generic family names are deliberately retained as in
the approved preview.

The old 97 bundled feature-card rules are not added to the default field names.
Existing custom `deck-rules.json` rules remain available as explicit label
overrides; `use_defaults: false` selects manual rules only. The file format is
unchanged. Database and label-table cache keys include file timestamps, sizes,
and inode information, allowing atomic updates to take effect on next query.

All archive presentation paths call the same `deck_name`: top-player listings,
individual decks, history, and share-link titles. No archive contents are
rewritten. `MyCard规则检查` reports the active field-table size and match policy.
