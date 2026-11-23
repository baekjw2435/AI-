# 강의 영상 자료: 표준사전 어인정 루트전

## 오프닝 (흰 바탕, 6초)

- `out/spqr_opening_white_1080p60.mp4`: 1920×1080, 60fps, H.264, 6.0초, 소리 없음. 강의 영상 맨 앞에 붙여 씁니다.
- 흐름: 붉은 리본 → 월계관 줄기가 아래에서 위로 그려지며 잎이 돋아남 → SPQR이 넓은 자간에서 모이며 선명해지고 금속 광이 흐름 → 금색 선 → 제목 글자가 떠오름 → 금빛이 글자 위를 스침 → 끝 글자 '전'이 붉게 물듦 → "끝말잇기 강의" → 반짝임.
- `out/opening_last_frame_1920x1080.png`: 마지막 장면 한 장.

## 썸네일

- `out/thumbnail_0강_OT_1280x720.jpg`(유튜브용, 68KB), 같은 그림의 `.png`, 큰 판 `out/thumbnail_0강_OT_1920x1080.png`.
- 오프닝의 마지막 장면 아래에 강 번호 배지("0강 · OT")를 넣은 것입니다.

## 다시 만들기

```sh
python3 eoinjeong_root/lecture/build_intro.py                    # intro.html
node eoinjeong_root/lecture/render_intro.js OUT_DIR "1강 · 후공이 이기는 음절"   # 영상 + 그 강의 썸네일
```

- `intro.html`은 CSS 애니메이션만 씁니다. `render_intro.js`가 모든 애니메이션을 멈추고 프레임마다 정확한 시각으로 맞춘 뒤 한 장씩 찍어 ffmpeg(libx264)로 묶습니다.
- `intro.html?mode=thumb&ep=…`는 애니메이션 없이 마지막 장면과 배지를 보여 줍니다(썸네일용).
- 글꼴은 Google Fonts의 나눔명조(제목)와 Noto Sans KR(배지)입니다.
