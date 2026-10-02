#!/usr/bin/env python3
"""Flexcil .flx → 필기가 입혀진 PDF (보기용). 원본 .flx는 읽기만 한다.
usage: flx2pdf.py <in.flx> <out.pdf>

형식(관찰 기반, Flexcil 데이터 버전 0.0.5). 좌표는 모두 **페이지 가로폭(W) 기준 0~1**이다(y도 W를 곱함).
  attachment/PDF/<id>            원본/노트 바탕 PDF
  attachment/image/<key>         붙인 이미지(PNG 등)
  pages.index                    페이지 목록: frame(pt), attachmentPage{file,index}, key
  objects/<page>.drawings        펜(type1)·형광펜(type2). start + points=b64[uint32 n][f32 (dx,dy,w)*n], strokeColor ARGB, figure1=직선
  objects/<page>.shapes          도형(type32). shapeType(1 사각형·4 다각형(sides)·7 화살표),  start + points(2점: 원점, (w,h)), strokeColor/fillColor ARGB, sides
  objects/<page>.images          이미지(type20). frame{x,y,width,height}, cropBox
  objects/<page>.texts           텍스트 상자(type30). frame, text, columns[].p.span[].style{font-size(W비율), color}
  objects/<page>.stickynotes     메모(type60). frame, text → PDF 메모 주석으로 넣음
  objects/<page>.maskings        마스킹(아직 미해석: 내용 있으면 경고)
"""
import sys, json, zipfile, base64, struct, fitz

WARN = []

def argb(c):
    return ((c >> 16) & 255) / 255, ((c >> 8) & 255) / 255, (c & 255) / 255, ((c >> 24) & 255) / 255

def hexcolor(h):
    h = h.lstrip('#'); return tuple(int(h[i:i+2], 16) / 255 for i in (0, 2, 4))

def load(z, name):
    try: return json.loads(z.read(name))
    except KeyError: return []

def pts3(b64):
    b = base64.b64decode(b64); n = struct.unpack('<I', b[:4])[0]
    v = struct.unpack(f'<{3*n}f', b[4:4+12*n]); return [(v[3*i], v[3*i+1], v[3*i+2]) for i in range(n)]

def draw_strokes(page, W, items):
    for s in items:
        if 'points' not in s: continue
        P = pts3(s['points']); sx, sy = s['start']['x'], s['start']['y']
        pts = [fitz.Point((sx+x)*W, (sy+y)*W) for x, y, _ in P]; ws = [w*W for _, _, w in P]
        r, g, b, a = argb(s.get('strokeColor', 0xFF000000))
        hl = s.get('type') == 2                        # 형광펜: 반투명·굵게·각진 끝
        sh = page.new_shape()
        if len(pts) == 1:
            sh.draw_circle(pts[0], max(ws[0], .3)/2); sh.finish(fill=(r, g, b), color=None, fill_opacity=a)
        elif hl:
            sh.draw_polyline(pts); sh.finish(color=(r, g, b), width=max(max(ws), .3), lineCap=0, lineJoin=1, stroke_opacity=a, closePath=False)
        else:
            for p, q, w in zip(pts, pts[1:], ws[1:]):
                sh.draw_line(p, q); sh.finish(color=(r, g, b), width=max(w, .3), lineCap=1, stroke_opacity=a)
        sh.commit()

def draw_shapes(page, W, items):
    import math
    for s in items:
        P = pts3(s['points']); sx, sy = s['start']['x']*W, s['start']['y']*W
        x0, y0 = sx + P[0][0]*W, sy + P[0][1]*W; x1, y1 = sx + P[-1][0]*W, sy + P[-1][1]*W
        lw = max(P[0][2]*W, .3)
        sr, sg, sb, sa = argb(s.get('strokeColor', 0xFF000000)); fill = s.get('fillColor', 0)
        fc = argb(fill) if fill else None
        R = fitz.Rect(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        sh = page.new_shape(); t = s.get('shapeType')
        if t == 7:                                                          # 화살표(시작→끝, 끝에 촉)
            sh.draw_line((x0, y0), (x1, y1))
            sh.finish(color=(sr, sg, sb), width=lw, lineCap=1, stroke_opacity=sa)
            L = math.hypot(x1 - x0, y1 - y0) or 1; ux, uy = (x1 - x0) / L, (y1 - y0) / L
            h = max(lw * 4, min(14, L * .3)); wv = h * .6                   # 열린 촉(->): 선 두 개
            bx, by = x1 - ux * h, y1 - uy * h
            sh.draw_polyline([(bx - uy * wv, by + ux * wv), (x1, y1), (bx + uy * wv, by - ux * wv)])
            sh.finish(color=(sr, sg, sb), width=lw, lineCap=1, lineJoin=1, stroke_opacity=sa, closePath=False)
            sh.commit(); continue
        elif t == 1: sh.draw_rect(R)                                        # 사각형(추정)
        elif t == 2: sh.draw_oval(R)                                        # 원/타원(추정)
        elif t == 4:                                                        # 다각형(sides)
            k = s.get('sides', 5); c = (R.x0+R.x1)/2, (R.y0+R.y1)/2; rx, ry = R.width/2, R.height/2
            poly = [fitz.Point(c[0]+rx*math.cos(-math.pi/2+2*math.pi*i/k), c[1]+ry*math.sin(-math.pi/2+2*math.pi*i/k)) for i in range(k)]
            sh.draw_polyline(poly + [poly[0]])
        else:
            sh.draw_rect(R); WARN.append(f'알 수 없는 도형 shapeType={t} → 사각형으로 표시')
        sh.finish(color=(sr, sg, sb), width=lw, fill=fc[:3] if fc else None, fill_opacity=fc[3] if fc else 1, stroke_opacity=sa)
        sh.commit()

def draw_images(page, W, z, items):
    for im in items:
        f = im['frame']; R = fitz.Rect(f['x']*W, f['y']*W, (f['x']+f['width'])*W, (f['y']+f['height'])*W)
        try: page.insert_image(R, stream=z.read('attachment/image/' + im['key']), keep_proportion=False)
        except KeyError: WARN.append('이미지 파일 없음 ' + im['key'])
        if im.get('cropBox', {}) not in ({}, {"y": 0.0, "x": 0.0, "width": 1.0, "height": 1.0}) or im.get('freeCrops'):
            WARN.append('이미지 자르기(crop)는 반영 안 됨')

def draw_texts(page, W, items):
    for t in items:
        f = t['frame']; R = fitz.Rect(f['x']*W, f['y']*W, (f['x']+f['width'])*W, (f['y']+f['height'])*W)
        size, color = 12, (0, 0, 0)
        try:
            st = t['columns'][0]['p']['span'][0]['style']; size = st.get('font-size', .016)*W; color = hexcolor(st.get('color', '#000000'))
        except (KeyError, IndexError): pass
        R.y1 = max(R.y1, R.y0 + size*1.6)
        rc = page.insert_textbox(R, t.get('text', ''), fontsize=size, fontname='korea', color=color)
        if rc < 0: page.insert_textbox(fitz.Rect(R.x0, R.y0, R.x1 + W*.3, R.y1 + size*3), t.get('text', ''), fontsize=size, fontname='korea', color=color)

def add_notes(page, W, items):
    for n in items:
        f = n['frame']; a = page.add_text_annot(fitz.Point(f['x']*W, f['y']*W), n.get('text', ''), icon='Note'); a.update()

def convert(src, dst):
    z = zipfile.ZipFile(src); out = fitz.open(); pdfs = {}
    for pg in json.loads(z.read('pages.index')):
        ap = pg.get('attachmentPage')
        if ap:
            f = ap['file']
            if f not in pdfs: pdfs[f] = fitz.open('pdf', z.read(f'attachment/PDF/{f}'))
            out.insert_pdf(pdfs[f], from_page=ap['index'], to_page=ap['index']); page = out[-1]
        else:
            page = out.new_page(width=pg['frame']['width'], height=pg['frame']['height'])
        W = page.rect.width; K = f"objects/{pg['key']}"
        draw_images(page, W, z, load(z, K + '.images'))
        draw_shapes(page, W, load(z, K + '.shapes'))
        draw_strokes(page, W, load(z, K + '.drawings'))
        draw_texts(page, W, load(z, K + '.texts'))
        add_notes(page, W, load(z, K + '.stickynotes'))
        if load(z, K + '.maskings'): WARN.append('마스킹 펜 내용이 있음(미지원)')
    out.save(dst, garbage=3, deflate=True)
    for w in sorted(set(WARN)): print('경고:', w, file=sys.stderr)

if __name__ == '__main__':
    convert(sys.argv[1], sys.argv[2])
