"""4g 정답 준비: 원문 PDF의 쪽을 PNG로 뽑아 표·설명을 눈으로 확인한다(읽기 전용)."""
import sys
import pymupdf
PDF = r'C:\Users\user\Desktop\PROJECTS\civilai-construction-risk-agent\data\raw\standard_estimation\2026_건설공사표준품셈_원문_정오표1차_반영.pdf'
out = sys.argv[1]
pages = [int(x) for x in sys.argv[2:]]
doc = pymupdf.open(PDF)
print('pages', len(doc))
for p in pages:
    pg = doc[p - 1]
    pg.get_pixmap(dpi=110).save(f'{out}/p{p}.png')
    print('saved', p)
