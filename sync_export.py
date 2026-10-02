#!/usr/bin/env python3
"""Flexcil 동기화 폴더 → 폴더 구조 그대로 필기 PDF로 내보내기 (바뀐 문서만).
usage: sync_export.py <Flexcil 동기화 폴더> <출력 폴더>
- documents.list(8바이트 길이 + raw deflate JSON 트리)로 폴더/문서 이름을 읽는다.
- 원본(.flx, .list)은 읽기만 한다. 출력 폴더의 PDF는 .flx가 더 새로울 때만 다시 만든다.
- 출력 폴더는 Flexcil 앱과 **완전히 같은 구조**(PDF만)로 유지한다: 앱에서 지운 문서·폴더는 출력에서도 지운다.
  (지운 것의 보관은 NAS로 보낼 때 rsync --backup-dir 이 맡는다)
"""
import sys, os, json, zlib, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flx2pdf

def read_list(p):
    b = open(p, 'rb').read(); return json.loads(zlib.decompress(b[8:], -15))

def safe(name):
    return re.sub(r'[\\/:*?"<>|]', '_', name).strip() or '이름없음'

FOLDERS = []
def walk(items, path=()):
    for it in items:
        if it.get('state') != 'valid': continue
        if it.get('type') == 1:                      # 폴더 (빈 폴더도 만든다)
            FOLDERS.append(path + (safe(it['name']),))
            yield from walk(it.get('children', []), path + (safe(it['name']),))
        elif it.get('document'):
            yield path, it

def main(src, dst):
    docs = list(walk(read_list(os.path.join(src, 'documents.list'))))
    wanted, done, skip = set(), 0, 0
    for path, d in docs:
        flx = os.path.join(src, d['document'] + '.flx')
        out = os.path.join(dst, *path, safe(d['name']) + '.pdf')
        if out in wanted: out = out[:-4] + f" ({d['document'][:4]}).pdf"   # 같은 이름 충돌
        wanted.add(out)
        if not os.path.exists(flx): print('없음:', flx); continue
        if os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(flx): skip += 1; continue
        os.makedirs(os.path.dirname(out), exist_ok=True)
        flx2pdf.WARN.clear(); flx2pdf.convert(flx, out)
        ts = d.get('modifiedDate'); ts and os.utime(out, (ts, max(ts, os.path.getmtime(flx))))
        print('변환:', os.path.relpath(out, dst)); done += 1
    for f in FOLDERS: os.makedirs(os.path.join(dst, *f), exist_ok=True)
    # Flexcil에서 사라진 문서·폴더 → 출력에서도 제거 (앱과 동일 구조 유지)
    removed = 0
    for root, dirs, files in os.walk(dst, topdown=False):
        for f in files:
            p = os.path.join(root, f)
            if p not in wanted: os.remove(p); removed += 1; print('제거:', os.path.relpath(p, dst))
        rel = os.path.relpath(root, dst)
        if rel != '.' and tuple(rel.split(os.sep)) not in set(FOLDERS) and not os.listdir(root):
            os.rmdir(root); print('폴더 제거:', rel)
    print(f'완료: 변환 {done}, 변경없음 {skip}, 제거 {removed}, 전체 {len(docs)}')

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
