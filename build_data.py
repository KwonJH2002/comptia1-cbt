# 해설 PDF(연도별)를 파싱해 CBT 사이트용 data.js 와 img/ 를 생성한다.
# 사용법: python build_data.py  (컴활/CBT 폴더에서 실행)
import fitz, glob, json, os, re, hashlib

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(ROOT)
IMG_DIR = os.path.join(ROOT, 'img')
os.makedirs(IMG_DIR, exist_ok=True)

CIRC = '①②③④'
WRAP_X = 480          # 이 위치보다 오른쪽에서 끝난 줄은 자동 줄바꿈으로 간주
SUBJECTS = {1: '컴퓨터 일반', 2: '스프레드시트 일반', 3: '데이터베이스 일반'}


def line_text(l):
    return ''.join(s['text'] for s in l['spans'])


def items_of_page(page):
    """페이지의 텍스트 줄과 이미지를 y순으로 반환 (머리글/바닥글 제외)."""
    out = []
    for b in page.get_text('dict')['blocks']:
        y0 = b['bbox'][1]
        if y0 > 795 or y0 < 40:
            continue
        if b['type'] == 1:
            out.append(('img', b['bbox'], b))
        else:
            for l in b['lines']:
                t = line_text(l)
                if not t.strip():
                    continue
                out.append(('text', l['bbox'], t))
    out.sort(key=lambda it: (round(it[1][1]), it[1][0]))
    return out


def save_img(b, name):
    data = b['image']
    ext = b.get('ext', 'png')
    fn = f'{name}.{ext}'
    with open(os.path.join(IMG_DIR, fn), 'wb') as f:
        f.write(data)
    w = b['bbox'][2] - b['bbox'][0]
    return {'src': 'img/' + fn, 'w': round(w * 1.5)}


def parse_pdf(path, exams):
    doc = fitz.open(path)
    exam = None; q = None; field = None; subject = 0
    quick = None
    last = None   # (field_ref, x1) 이전 텍스트 줄

    def append(target_key, x0, x1, t, idx=None):
        nonlocal last
        if idx is None:
            cur = q[target_key]
        else:
            cur = q[target_key][idx]
        wrap = last is not None and last[1] > WRAP_X
        if cur == '':
            new = t
        elif wrap:
            # 영문 단어/문장 끝에서 줄바꿈되면 공백이 사라지므로 복원
            if re.search(r'[A-Za-z0-9.,?!;:)\]”’"]$', cur) and not re.match(r'[\s.,)\]]', t):
                new = cur + ' ' + t
            else:
                new = cur + t
        else:
            new = cur + '\n' + t
        if idx is None:
            q[target_key] = new
        else:
            q[target_key][idx] = new
        last = (target_key, x1)

    for pno, page in enumerate(doc):
        for kind, bbox, obj in items_of_page(page):
            x0, y0, x1, y1 = bbox
            if kind == 'img':
                if q is None:
                    continue
                name = f"{exam['id']}_{q['no']:02d}_{len(q['imgs']) + len(q['explImgs'])}"
                info = save_img(obj, name)
                if field == 'expl':
                    q['explImgs'].append(info)
                elif field == 'choice':
                    # 보기 사이 이미지: 해당 보기 뒤에 표시
                    info['after'] = len([c for c in q['choices'] if c]) - 1
                    q['imgs'].append(info)
                else:
                    q['imgs'].append(info)
                last = None
                continue

            t = obj
            m = re.match(r'^(\d{4})년 상시 (\d+)회$', t.strip())
            if m and x0 < 55:
                exam = {'id': f'{m.group(1)}-{int(m.group(2)):02d}', 'year': int(m.group(1)),
                        'round': int(m.group(2)), 'questions': [], 'quick': {}}
                exams.append(exam)
                q = None; field = None; quick = 'pending'; last = None
                continue
            if exam is None:
                continue
            if t.strip() == '빠른 정답표':
                quick = 'on'; continue
            if quick == 'on':
                mm = re.match(r'^(\d+) ([①②③④].*)$', t.strip())
                if mm:
                    exam['quick'][int(mm.group(1))] = mm.group(2); continue
            m = re.match(r'^제(\d)과목', t.strip())
            if m and x0 < 55:
                subject = int(m.group(1)); quick = None; continue
            m = re.match(r'^(\d+)\.\s*(.*)$', t)
            if m and 45 <= x0 <= 49:
                quick = None
                q = {'no': int(m.group(1)), 'subject': subject, 'stem': m.group(2),
                     'choices': ['', '', '', ''], 'imgs': [], 'answer': None,
                     'expl': '', 'explImgs': []}
                exam['questions'].append(q)
                field = 'stem'; last = ('stem', x1)
                continue
            if q is None:
                continue
            if 58 <= x0 <= 62 and t[0] in CIRC and field in ('stem', 'choice'):
                ci = CIRC.index(t[0])
                q['choices'][ci] = t[1:].strip()
                field = 'choice'; q['_ci'] = ci; last = ('choice', x1)
                continue
            m = re.match(r'^정답\s+(.+)$', t.strip())
            if m and 66 <= x0 <= 70 and field in ('choice', 'stem') :
                q['answer'] = m.group(1).strip()
                field = 'expl'; last = None
                continue
            # 이어지는 줄
            if field == 'stem':
                append('stem', x0, x1, t)
            elif field == 'choice':
                append('choices', x0, x1, t, q['_ci'])
            elif field == 'expl':
                append('expl', x0, x1, t)
    for e in exams:
        for qq in e['questions']:
            qq.pop('_ci', None)


def main():
    for f in glob.glob(os.path.join(IMG_DIR, '*')):
        os.remove(f)
    exams = []
    for path in sorted(glob.glob(os.path.join(SRC, '*', '*해설.pdf'))):
        parse_pdf(path, exams)
    problems = []
    for e in exams:
        nums = [q['no'] for q in e['questions']]
        if nums != list(range(1, 61)):
            problems.append(f"{e['id']}: 문항 번호 이상 {len(nums)}개")
        for q in e['questions']:
            # "(보기는 위 그림 참고 · 정답 ③)" 안내 줄은 정답이 노출되므로 제거
            lines = q['stem'].split('\n')
            kept = [l for l in lines if '보기는 위 그림' not in l]
            if len(kept) != len(lines):
                q['stem'] = '\n'.join(kept)
                q['choicesInImage'] = True
            if any(not c for c in q['choices']) and not q.get('choicesInImage'):
                problems.append(f"{e['id']} {q['no']}: 빈 보기")
            ans = q['answer'] or ''
            q['answerIdx'] = [CIRC.index(ch) for ch in ans if ch in CIRC]
            if not q['answerIdx']:
                problems.append(f"{e['id']} {q['no']}: 정답 해석 불가 '{ans}'")
            qa = e['quick'].get(q['no'])
            if qa and set(CIRC.index(ch) for ch in qa if ch in CIRC) != set(q['answerIdx']):
                problems.append(f"{e['id']} {q['no']}: 빠른정답표 {qa} vs 본문 {ans}")
        e.pop('quick')
    with open(os.path.join(ROOT, 'data.js'), 'w', encoding='utf-8') as f:
        f.write('window.CBT_DATA = ')
        json.dump(exams, f, ensure_ascii=False)
        f.write(';\n')
    print(len(exams), 'exams', sum(len(e['questions']) for e in exams), 'questions',
          len(os.listdir(IMG_DIR)), 'images')
    print('\n'.join(problems) or 'no problems')


if __name__ == '__main__':
    main()
