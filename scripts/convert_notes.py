#!/usr/bin/env python3
"""Convert Obsidian DevOps notes into VitePress pages for the advanced sections.

Usage:  python3 scripts/convert_notes.py <path-to-notes>/DevOps [--check]

For every section in SECTIONS it writes docs/<slug>/NN-name.md from
NN_name.md (+ NN_name_tasks.md merged in as «Задачи» with an answer under each
question) and refreshes the lesson descriptions in docs/<slug>/index.md from
the table in the section's 00_INDEX.md. Page titles come from the sidebar in
docs/.vitepress/config.mts. --check only reports what would change.
"""
import html
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / 'docs'

SECTIONS = {
    'Performance': 'performance', 'Storage': 'storage', 'Virtualization': 'virtualization',
    'Platform': 'platform', 'SRE': 'sre', 'Distributed': 'distributed', 'Security': 'security',
    'FinOps': 'finops', 'MLOps': 'mlops', 'Python': 'python', 'Project': 'project',
    'Career': 'career', 'Leadership': 'leadership', 'SoftSkills': 'softskills', 'English': 'english',
}
OTHER_SECTIONS = {
    'Git': 'git', 'Linux': 'linux', 'Network': 'network', 'Docker': 'docker', 'CICD': 'cicd',
    'Ansible': 'ansible', 'Kubernetes': 'kubernetes', 'Left/01_Databases': 'databases',
    'Left/02_Monitoring': 'monitoring', 'Left/03_Logging': 'logging', 'Left/04_Cloud': 'cloud',
    'Left/05_Queues': 'queues', 'Left/06_Terraform': 'terraform', 'Left/07_ArgoCD': 'argocd',
    'Left/08_Vault': 'vault',
}
SHORT_NAMES = {
    'git': 'Git', 'linux': 'Linux', 'network': 'Сети', 'docker': 'Docker', 'cicd': 'CI/CD',
    'ansible': 'Ansible', 'kubernetes': 'Kubernetes', 'databases': 'Базы данных',
    'monitoring': 'Мониторинг', 'logging': 'Логирование', 'cloud': 'Облака', 'queues': 'Очереди',
    'terraform': 'Terraform', 'argocd': 'ArgoCD', 'vault': 'Vault', 'performance': 'Performance',
    'storage': 'Хранилища', 'virtualization': 'Виртуализация', 'platform': 'Platform Engineering',
    'sre': 'SRE', 'distributed': 'Распределённые системы', 'security': 'Безопасность',
    'finops': 'FinOps', 'mlops': 'MLOps', 'python': 'Python', 'project': 'Пет-проект',
    'career': 'Карьера', 'leadership': 'Leadership', 'softskills': 'Soft Skills',
    'english': 'English',
}
HTML_TAGS = {
    'a', 'b', 'br', 'code', 'details', 'div', 'em', 'i', 'img', 'kbd', 'li', 'mark', 'ol', 'p',
    'pre', 'small', 'span', 'strong', 'sub', 'summary', 'sup', 'table', 'tbody', 'td', 'th',
    'thead', 'tr', 'u', 'ul',
}
FENCE = re.compile(r'^( {0,3})(`{3,}|~{3,})(.*)$')
CODE_SPAN = re.compile(r'(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)', re.S)
LINK = re.compile(r'\[([^\]\n]*)\]\(([^)\s]+)\)')
DIAGRAM = re.compile(r'[─│┌┐└┘├┤┬┴┼═║►▶▼▲◄←→↑↓]')
CYR = str.maketrans('АВСЕ', 'ABCE')

warnings = []


def warn(msg):
    warnings.append(msg)


# ---------------------------------------------------------------- titles ----
def sidebar_titles():
    cfg = (DOCS / '.vitepress/config.mts').read_text()
    titles = {}
    for m in re.finditer(r"\{\s*text:\s*(['\"])(.*?)\1,\s*link:\s*'([^']+)'\s*\}", cfg):
        text, link = m.group(2).replace("\\'", "'"), m.group(3)
        if text != 'Обзор темы':
            titles.setdefault(link, text)
    return titles


TITLES = sidebar_titles()


# ----------------------------------------------------------------- links ----
def site_path(src_rel):
    """'Linux/14_process_utilization.md' -> ('/linux/14-process-utilization', is_tasks)."""
    src_rel = src_rel.removesuffix('.md')
    folder, _, name = src_rel.rpartition('/')
    slug = SECTIONS.get(folder) or OTHER_SECTIONS.get(folder)
    if not slug:
        return None
    if name == '00_INDEX':
        return f'/{slug}/', False
    tasks = name.endswith('_tasks')
    page = name.removesuffix('_tasks').replace('_', '-')
    if not (DOCS / slug / f'{page}.md').exists():
        return None
    return f'/{slug}/{page}', tasks


class Linker:
    def __init__(self, notes_root):
        self.root = notes_root
        self.by_name = {}
        for p in notes_root.rglob('*.md'):
            self.by_name.setdefault(p.name, []).append(p.relative_to(notes_root).as_posix())

    def locate(self, ref, cur_folder):
        """Path of the referenced note relative to the notes root, or None."""
        ref = ref.split('#')[0]
        if not ref.endswith('.md'):
            return None
        ref = re.sub(r'^(\./)?(Life/)?(DevOps/)?', '', ref)
        parts = []
        for seg in pathlib.PurePosixPath(cur_folder, ref).parts:
            if seg == '..':
                if parts:
                    parts.pop()
            elif seg != '.':
                parts.append(seg)
        norm = re.sub(r'^(Life/)?DevOps/', '', '/'.join(parts))
        for c in (norm, ref):
            if (self.root / c).exists():
                return c
        name = ref.rsplit('/', 1)[-1]
        hits = self.by_name.get(name, [])
        if name == '00_INDEX.md':
            hits = [h for h in hits if h.startswith(ref.rsplit('/', 2)[-2] + '/')] if '/' in ref else []
        return hits[0] if len(hits) == 1 else None

    def resolve(self, ref, cur_folder):
        src = self.locate(ref, cur_folder)
        return site_path(src) if src else None

    def title(self, path, tasks, cur_slug):
        slug = path.strip('/').split('/')[0]
        if path.endswith('/'):
            return SHORT_NAMES[slug]
        t = TITLES.get(path, path)
        if tasks:
            t += ' — задачи'
        return t if slug == cur_slug else f'{SHORT_NAMES[slug]}: {t}'

    def link(self, m, cur_folder, cur_slug):
        text, target = m.group(1), m.group(2)
        if target.startswith('file:'):
            return f'`{text}`'
        if re.match(r'^(https?|mailto):', target):
            return m.group(0)
        resolved = None
        text_is_path = bool(re.search(r'\.md(#.*)?$', text.strip('` ')))
        if text_is_path:
            resolved = self.resolve(text.strip('` '), cur_folder)
        resolved = resolved or self.resolve(target, cur_folder)
        if not resolved:
            src = self.locate(text.strip('` ') if text_is_path else target, cur_folder)
            if src:  # a note that is not published on the site: name it, no link
                h1 = (self.root / src).read_text().split('\n', 1)[0]
                return '«' + re.sub(r'^#\s*(\W+\s)?', '', h1).strip() + '»'
            warn(f'{cur_folder}: unresolved link {m.group(0)}')
            return text if not text_is_path else f'`{text}`'
        path, tasks = resolved
        href = path + ('#задачи' if tasks else '')
        label = self.title(path, tasks, cur_slug) if text_is_path else text
        return f'[{label}]({href})'


# -------------------------------------------------------------- escaping ----
def escape_text(s):
    """Plain markdown text (no code spans): keep known HTML, escape the rest for Vue."""
    def tag(m):
        name = m.group(2).lower()
        if name in HTML_TAGS or name in ('http', 'https', 'mailto'):
            return m.group(0)
        return '&lt;' + m.group(0)[1:]
    s = re.sub(r'<(/?)([A-Za-zА-Яа-яЁё][\w-]*)', tag, s)
    return s.replace('{{', '<span v-pre>{{</span>').replace('}}', '<span v-pre>}}</span>')


def code_span(ticks, body):
    if '{{' not in body and '}}' not in body:
        return ticks + body + ticks
    enc = body.strip() if len(ticks) > 1 else body
    enc = enc.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    enc = re.sub(r'(?<!\\)([*_\[\]`~])', r'\\\1', enc)
    return f'<code v-pre>{enc}</code>'


def convert_line(line, linker, cur_folder, cur_slug):
    spans = []

    def stash(m):
        spans.append((m.group(1), m.group(2)))
        return f'\x00{len(spans) - 1}\x00'

    s = CODE_SPAN.sub(stash, line)
    # links may contain code spans in their text: restore those for matching
    s = LINK.sub(lambda m: '\x01' + linker.link(
        re.match(LINK, re.sub(r'\x00(\d+)\x00', lambda k: ''.join(
            (spans[int(k.group(1))][0], spans[int(k.group(1))][1], spans[int(k.group(1))][0])), m.group(0))),
        cur_folder, cur_slug) + '\x02', s)
    out = []
    for part in re.split(r'(\x01.*?\x02)', s):
        if part.startswith('\x01'):
            out.append(part[1:-1])
        else:
            out.append(escape_text(part))
    s = ''.join(out)
    return re.sub(r'\x00(\d+)\x00', lambda k: code_span(*spans[int(k.group(1))]), s)


def convert_body(lines, linker, cur_folder, cur_slug):
    out, i = [], 0
    while i < len(lines):
        m = FENCE.match(lines[i])
        if m:
            indent, fence, info = m.groups()
            j = i + 1
            while j < len(lines):
                c = FENCE.match(lines[j])
                if c and c.group(2)[0] == fence[0] and len(c.group(2)) >= len(fence) and not c.group(3).strip():
                    break
                j += 1
            body = lines[i + 1:j]
            if not info.strip() and any(DIAGRAM.search(b) for b in body):
                info = 'text:no-line-numbers'
            out.append(indent + fence + info.strip())
            out.extend(body)
            out.append(indent + fence)
            if j >= len(lines):
                warn(f'{cur_folder}: unclosed fence at line {i + 1}')
            i = j + 1
            continue
        # an inline code span may continue on the next line of the same paragraph
        j = i
        ticks = lines[i].count('`')
        while ticks % 2 and j + 1 < len(lines) and lines[j + 1].strip() and not FENCE.match(lines[j + 1]):
            j += 1
            ticks += lines[j].count('`')
        chunk = '\n'.join(lines[i:j + 1])
        out.extend(convert_line(chunk, linker, cur_folder, cur_slug).split('\n'))
        i = j + 1
    return out


# ----------------------------------------------------------------- tasks ----
def outside_fence_flags(lines):
    """For each line: True when it is plain markdown (not inside/at a code fence)."""
    flags, open_ = [], None
    for l in lines:
        m = FENCE.match(l)
        if open_ is None and m:
            open_ = (m.group(2)[0], len(m.group(2)))
            flags.append(False)
        elif open_ and m and m.group(2)[0] == open_[0] and len(m.group(2)) >= open_[1] and not m.group(3).strip():
            open_ = None
            flags.append(False)
        else:
            flags.append(open_ is None)
    return flags


BLOCK_H = re.compile(r'^## Блок\s+([A-ZА-Я])\b')
BOLD_ID = re.compile(r'^\*\*([A-ZА-Я])(\d+)\.?\*\*\s?')
HEAD_ID = re.compile(r'^(#{3,4}) ([A-ZА-Я])(\d+)\.')
NUM_ID = re.compile(r'^(\d+)\.\s')


def split_blocks(lines):
    """-> [(letter|None, [lines])] split on '## Блок X' headings outside fences."""
    flags = outside_fence_flags(lines)
    blocks, cur, letter = [], [], None
    for l, plain in zip(lines, flags):
        m = BLOCK_H.match(l) if plain else None
        if m:
            blocks.append((letter, cur))
            cur, letter = [], m.group(1).translate(CYR)
        cur.append(l)
    blocks.append((letter, cur))
    return blocks


def split_items(lines, letter, numbered_ok, headings_end=True):
    """Split a block into (key|None, lines). Keys come from **A1.**, ### C1. or, if the
    block has neither, top-level numbered list items."""
    flags = outside_fence_flags(lines)
    has_ids = any(p and (BOLD_ID.match(l) or HEAD_ID.match(l)) for l, p in zip(lines, flags))
    items, cur, key = [], [], None
    for l, plain in zip(lines, flags):
        k = None
        if plain:
            if m := BOLD_ID.match(l):
                k = (m.group(1).translate(CYR), int(m.group(2)))
            elif m := HEAD_ID.match(l):
                k = (m.group(2).translate(CYR), int(m.group(3)))
            elif not has_ids and numbered_ok and (m := NUM_ID.match(l)):
                k = (letter, int(m.group(1)))
            elif key and re.match(r'^#{1,3} ' if headings_end else r'^#{1,2} ', l):
                items.append((key, cur))
                cur, key = [], None
        if k:
            items.append((key, cur))
            cur, key = [], k
        cur.append(l)
    items.append((key, cur))
    return [(k, ls) for k, ls in items if ls or k]


def answer_text(lines):
    first = lines[0]
    if m := BOLD_ID.match(first):
        rest = first[m.end():]
        body = ([rest] if rest.strip() else []) + lines[1:]
    elif m := NUM_ID.match(first):
        w = m.end()
        body = [first[w:]] + [l[w:] if l[:w].strip() == '' else l for l in lines[1:]]
    else:
        body = lines
    while body and not body[0].strip():
        body.pop(0)
    while body and (not body[-1].strip() or body[-1].strip() == '---'):
        body.pop()
    if body:  # «1) …» right after the label is inline numbering, not a list
        body[0] = re.sub(r'^(\d+)\) ', r'\1\\) ', body[0])
    return body


def merge_tasks(text):
    lines = text.split('\n')
    flags = outside_fence_flags(lines)
    try:
        cut = next(i for i, (l, p) in enumerate(zip(lines, flags)) if p and re.match(r'^# .*Ответы', l))
    except StopIteration:
        warn('tasks without answers section')
        cut = len(lines)
    questions, answers = lines[:cut], lines[cut + 1:]

    # answers: drop the <details> wrapper, split off the checklist
    aflags = outside_fence_flags(answers)
    checklist = []
    for i, (l, p) in enumerate(zip(answers, aflags)):
        if p and l.startswith('## 🎯'):
            answers, checklist = answers[:i], answers[i:]
            break
    answers = [l for l in answers if l.strip() not in ('<details>', '</details>', '<summary>Раскрыть</summary>')]
    amap = {}
    for letter, blines in split_blocks(answers):
        if letter is None:
            continue
        for key, ilines in split_items(blines[1:], letter, numbered_ok=True, headings_end=False):
            if key:
                amap[key] = answer_text(ilines)
            elif any(l.strip() for l in ilines):
                warn(f'answer text outside any item in block {letter}: {ilines[0][:60]!r}')

    # header: H1 + blockquote without the «Конспект:» back-link
    body_start = next(i for i, l in enumerate(questions) if l.startswith('# '))
    out = []
    used = set()
    for letter, blines in split_blocks(questions[body_start + 1:]):
        if letter is None:
            out.extend(l for l in blines if not l.startswith('> Конспект:'))
            continue
        block_start = len(out)
        for key, ilines in split_items(blines, letter, numbered_ok=True):
            if not key:
                out.extend(ilines)
                continue
            tail = []
            while ilines and (not ilines[-1].strip() or ilines[-1].strip() == '---'):
                tail.insert(0, ilines.pop())
            first = ilines[0]
            if (m := NUM_ID.match(first)) and not BOLD_ID.match(first):
                w = m.end()
                ilines = [f'**{m.group(1)}.** {first[w:]}'] + [
                    l[w:] if l[:w].strip() == '' else l for l in ilines[1:]]
            out.extend(ilines)
            if key in amap:
                used.add(key)
                out += ['', '<details><summary>Ответ</summary>', ''] + amap[key] + ['', '</details>']
            elif key[0] != 'C':  # C tasks may be open-ended, without an answer
                warn(f'no answer for {key[0]}{key[1]}')
            out.extend(tail or [''])
        # questions that live in one code block (B1. … B12.): one <details> for the block
        rest = sorted(k for k in amap.keys() - used if k[0] == letter)
        if rest:
            tail = []
            while len(out) > block_start and (not out[-1].strip() or out[-1].strip() == '---'):
                tail.insert(0, out.pop())
            out += ['', '<details><summary>Ответы</summary>', '']
            for k in rest:
                used.add(k)
                ans = amap[k]
                label = f'**{k[0]}{k[1]}.**'
                if ans and not re.match(r'^(\s*```|\s*[-*] |\s*\d+\. |\||>)', ans[0]):
                    out += [f'{label} {ans[0]}'] + ans[1:] + ['']
                else:
                    out += [label, ''] + ans + ['']
            out += ['</details>'] + (tail or [''])
    for key in amap.keys() - used:
        warn(f'answer without question: {key[0]}{key[1]}')
    if checklist:
        out += ['', '---', ''] + checklist
    # one heading level down: «## Блок» -> «### Блок», «### C1.» -> «#### C1.»
    oflags = outside_fence_flags(out)
    return [('#' + l if p and re.match(r'^#{1,5} ', l) else l) for l, p in zip(out, oflags)]


# ----------------------------------------------------------------- pages ----
DESC_COLUMNS = ('Ключевой навык', 'Что там', 'Навык для резюме')


def index_descriptions(index_md):
    """Lesson descriptions from the tables in 00_INDEX.md, keyed by note file stem."""
    descs, header = {}, []
    for l in index_md.split('\n'):
        if not l.startswith('|'):
            header = []
            continue
        cells = [c.strip() for c in l.strip().strip('|').split('|')]
        if not header:
            header = cells
            continue
        m = re.search(r"\]\((?:[^)]*/)?(\d\d_[^)/]+?)\.md\)", l)
        cols = [header.index(h) for h in DESC_COLUMNS if h in header]
        if m and cols and not m.group(1).endswith('_tasks') and len(cells) == len(header):
            descs.setdefault(m.group(1), re.sub(r'[`*]', '', cells[cols[0]]))
    return descs


def frontmatter(path):
    if not path.exists():
        return {}
    t = path.read_text()
    m = re.match(r'^---\n(.*?)\n---\n', t, re.S)
    fm = {}
    for l in (m.group(1).split('\n') if m else []):
        k, _, v = l.partition(':')
        fm[k.strip()] = json.loads(v.strip()) if v.strip().startswith('"') else v.strip()
    return fm


def strip_footer(lines):
    lines = [l for l in lines if not l.startswith('➡️ Дальше')]
    while lines and (not lines[-1].strip() or lines[-1].strip() == '---'):
        lines.pop()
    return lines


def build_page(src, tasks, slug, folder, linker, desc):
    dest = DOCS / slug / (src.stem.replace('_', '-') + '.md')
    old = frontmatter(dest)
    notes = strip_footer(src.read_text().split('\n'))
    title = TITLES.get(f'/{slug}/{dest.stem}') or old.get('title') or notes[0].lstrip('# ')
    description = desc or old.get('description', '')
    body = convert_body(notes, linker, folder, slug)
    if tasks:
        warnings_before = len(warnings)
        merged = merge_tasks(tasks.read_text())
        for i in range(warnings_before, len(warnings)):
            warnings[i] = f'{slug}/{dest.stem}: {warnings[i]}'
        body += ['', '---', '', '## Задачи', ''] + convert_body(merged, linker, folder, slug)
    text = '\n'.join(['---', f'title: {json.dumps(title, ensure_ascii=False)}',
                      f'description: {json.dumps(description, ensure_ascii=False)}', '---', ''] + body)
    text = re.sub(r'\n{3,}', '\n\n', text).rstrip('\n') + '\n'
    return dest, text


def build_index(slug, descs):
    dest = DOCS / slug / 'index.md'
    text = dest.read_text()
    m = re.search(r'const lessons = (\[.*?\])\n</script>', text, re.S)
    if not m:
        return dest, text
    try:
        lessons = json.loads(re.sub(r',\s*\]$', ']', m.group(1)))
    except json.JSONDecodeError:
        warn(f'{slug}/index.md: lessons array is not JSON, left as is')
        return dest, text
    for les in lessons:
        key = les['link'].rsplit('/', 1)[-1].replace('-', '_')
        if key in descs:
            les['desc'] = descs[key]
    rows = ',\n'.join('  ' + json.dumps(les, ensure_ascii=False) for les in lessons)
    return dest, text.replace(m.group(1), '[\n' + rows + ',\n]')


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    notes_root = pathlib.Path(sys.argv[1]).expanduser()
    check = '--check' in sys.argv
    linker = Linker(notes_root)
    changed = 0
    for folder, slug in SECTIONS.items():
        src_dir = notes_root / folder
        index_md = (src_dir / '00_INDEX.md').read_text()
        descs = index_descriptions(index_md)
        pages = [build_index(slug, descs)]
        for src in sorted(src_dir.glob('[0-9][0-9]_*.md')):
            if src.stem.endswith('_tasks') or src.stem == '00_INDEX':
                continue
            tasks = src.with_name(src.stem + '_tasks.md')
            pages.append(build_page(src, tasks if tasks.exists() else None, slug, folder,
                                    linker, descs.get(src.stem)))
        for dest, text in pages:
            if not dest.exists() or dest.read_text() != text:
                changed += 1
                if not check:
                    dest.write_text(text)
    print(f'{"would change" if check else "changed"}: {changed} files')
    for w in warnings:
        print('  warning:', w)


if __name__ == '__main__':
    main()
