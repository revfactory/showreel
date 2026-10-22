# 이미지: 생성·실제 사진·누끼·후처리

## 목차

- 어떤 이미지를 쓸지 정하기
- codex-image로 생성하기
- 사람이 나오는 사진풍 이미지(photoreal)
- 실제 대상을 닮게 만들기(참조 이미지)
- 실제 사진 쓰기
- 후처리와 확인
- 영상에 넣는 방식

## 어떤 이미지를 쓸지 정하기

| 상황 | 쓸 이미지 |
| --- | --- |
| 실존 인물 소개 | 실제 사진만(사용자 제공·공식·보도). 분위기 컷(무대, 사무실, 도시 야경)은 얼굴 없이 생성 |
| 기업·제품 | 공식 로고·제품 화면 + 코드로 그린 UI 목업. 생성 이미지는 배경 질감으로 |
| 행사 | 생성 인물은 뒷모습·실루엣·군중. 연사는 실명·소속 텍스트만 |
| 연구·데이터 | 코드로 그린 도식(캔버스·SVG). "설명을 위해 그린 그림" 고지 |
| 반려동물·제품 | 실제 사진을 참조로 붙여 같은 대상을 새 장면에 생성(`codex_ref_image.sh`) |
| 이미지 없이 | 타이포·도형·파티클·데이터 시각화만으로 구성 |

실존 인물의 얼굴은 생성하지 않는다. 사칭이나 오해를 부를 수 있다. 사용자가 "realphoto(photoreal)로 인물 사진을 만들어"라고 해도, 실존 인물이면 실제 사진을 쓰고 생성은 가상 인물·뒷모습에만 쓴다고 알린다.

## codex-image로 생성하기

```bash
~/.claude/skills/codex-image/scripts/codex_imagegen_batch.sh <프로젝트>/assets/gen \
  "<프롬프트>::01_stage.png" "<프롬프트>::02_city.png" ...
```

- 5장씩 병렬로 돌고 장당 약 1분 걸린다. Bash `run_in_background`로 돌리고 그동안 다른 작업을 한다. 동시 생성 수는 스크립트에 5로 고정돼 있으니, 줄여야 하면(다른 작업과 사용량을 나눌 때) 한 번에 넘기는 항목 수를 줄인다.
- 결과는 `assets/gen/`에, 로그는 `assets/gen/.codex-imagegen-logs/`에 남는다.
- 실패("model is at capacity")한 것만 다시 돌린다. 이미 있는 파일은 목록에서 빼고 실행한다.
- 해상도는 약 1.57MP다(16:9는 1672×941, 3:2는 1536×1024). 영상에서는 `prep_images.py`로 2400px까지 키운다.

### 프롬프트 틀

한 구간의 컷에는 같은 **공통 꼬리**를 붙여 톤을 맞춘다. 꼬리에 넣는 빛·팔레트·질감 문구는 그 구간의 `concept.md` 아트 디렉션을 영어로 옮겨 적는다.

```
<장면 묘사: 장소·대상·구도·빛>. <concept.md 구간의 빛·팔레트·질감을 영어로>, wide 16:9 landscape frame,
large empty negative space on the left for typography, absolutely no text, no letters, no logos, no watermark
```

- 비율은 "wide 16:9 landscape frame"처럼 말로 적는다. "16:9 (1536x1024)"처럼 비율과 해상도가 어긋나게 쓰면 모델이 위아래에 검은 띠를 그려 넣는다(`prep_images.py`가 잘라 내지만 해상도를 잃는다).
- 글자를 올릴 자리(negative space)를 지정한다. 인물·사물은 화면 3분의 1에 둔다.
- 화면 속 모니터·간판은 "blank glowing screens with abstract color only"처럼 글자가 없게 한다. 한글 글자는 거의 항상 뭉개진다.
- 사람은 "seen only from behind as silhouettes, no faces visible"로 쓴다.
- 이미지 안에 그래픽을 합성할 자리를 비워 둘 수 있다: "the screen is pure deep black, reserved for compositing graphics later"

예시(실제 사용):

```
Cinematic photoreal still of a television broadcast master control room at night during a live show. A long wall of dozens of
glowing monitors showing blurred colorful stage images, a wide mixing console with hundreds of small illuminated buttons in the
foreground, two crew members seen only from behind as dark silhouettes with headsets, faces not visible. Only practical light from
the screens and console, deep shadows, slight haze, subtle film grain, slightly off-center framing. No readable text, no logos, no letters anywhere.
```

## 사람이 나오는 사진풍 이미지(photoreal)

가상 인물이 나오는 실사풍 컷은 `photoreal` 스킬을 먼저 읽고 프롬프트를 만든다. 광고 화보처럼 매끈한 결과를 피하고 스마트폰 스냅처럼 보이게 하는 지시가 정리돼 있다.

```bash
python3 ~/.claude/skills/photoreal/scripts/build_prompt.py --subject "30대 한국인 엔지니어 세 명" --scene office \
  --n 3 --level standard --lang en --emit-batch <프로젝트>/assets/gen
```

- 카메라 스펙(85mm, f/1.4)을 적으면 화보 쪽으로 간다.
- "nobody looking at the camera", "framing tilted a degree or two", "phone camera noise"가 자연스러움에 효과가 있었다.
- 생성 뒤 손가락 수, 눈동자, 글자 섞임, 나이를 확인한다.

## 실제 대상을 닮게 만들기(참조 이미지)

codex-image 배치 스크립트는 참조 이미지를 받지 않는다. 반려동물·제품·캐릭터처럼 실제 대상을 새 장면에 넣을 때는 이 스크립트를 쓴다.

```bash
sips -Z 1024 photo.jpg --out <프로젝트>/assets/refs/ref1.jpg      # 참조는 긴 변 1024px 로
bash $S/codex_ref_image.sh <프로젝트>/assets/gen/g01.png \
  "<신원 특징을 글로 다시 적기> + <장면> + 가로 16:9 구도, 글자·로고 없음" <프로젝트>/assets/refs/ref1.jpg
```

- 신원 특징(털 무늬, 눈 색, 목걸이, 제품 색·형태)을 글로 다시 적어야 일관성이 유지됐다.
- 한 장을 먼저 시험한 뒤 나머지를 최대 5개씩 백그라운드로 돌린다. 이미 만든 파일은 건너뛴다.

## 실제 사진 쓰기

- 출처를 `research/photos.md`에 표로 남긴다: 파일명 · 원본 URL · 기사 URL · 해상도 · 내용 · 품질.
- 받은 사진을 Read로 열어 본인인지 확인한다. 동명이인을 걸러 낸다.
- 보도 사진·위촉장·명패처럼 서명·직인이 보이는 사진은 납품 보고에 "공개 전 확인"으로 표시한다.
- 해상도가 낮은 기사 사진(500~800px)은 카드·폴라로이드 크기로만 쓰고, 전체 화면 배경에는 흐리게 처리해 쓴다.

## 후처리와 확인

```bash
python3 scripts/prep_images.py <프로젝트>/assets/gen <프로젝트>/assets/photos --out <프로젝트>/assets/img [--blur] [--cutout]
python3 scripts/prep_images.py --sheet <프로젝트>/assets/img --out <프로젝트>/qa/sheet_images.png
```

- 레터박스 검은 띠를 자동으로 잘라 내고, 긴 변 2400px로 맞추고, JPG 품질 92로 저장한다.
- `--blur`: 전환·배경용 흐린 버전(`_blur.jpg`)
- `--cutout`: macOS Vision으로 인물·피사체 누끼(`_cut.png`). 원본 픽셀은 바꾸지 않고 배경만 투명하게 한다. 처음 한 번 Swift로 컴파일한다.
- 시트를 Read로 보고 다음을 다시 만든다: 손가락·얼굴 이상, 글자·로고 섞임, 팔레트에서 벗어난 컷, 레터박스가 남은 컷.
- 누끼마다 인물 크기와 위치가 다르면 연속으로 보여 줄 때 화면이 튄다. 알파 채널에서 머리 위치와 폭을 계산해 크기를 맞춘다.

## 영상에 넣는 방식

| 기법 | 쓰는 곳 |
| --- | --- |
| 켄 번스(scale 1.08→1.18, 느린 이동) | 사진을 오래 보여 주는 장면에서 멈춘 사진이 슬라이드처럼 보일 때 |
| 3D 기울인 카드 + 클립 와이프 | 경력·자료 카드, 폴라로이드 |
| 누끼 + 림라이트(누끼를 마스크로 구간 팔레트의 빛을 인물 안쪽 가장자리에만) | 인물 공개, 이름 카드 |
| 글자 안에 사진 채우기(`background-clip: text`) | 오프닝 키워드 |
| 흐리고 어둡게(blur 6~10px, brightness 0.5) | 글자 뒤 배경 질감 |
| 듀오톤·틴트(`mix-blend-mode: color`) | 장면 색을 팔레트에 맞출 때 |

글자를 사진 위에 올릴 때는 글자 쪽에 어두운 그라디언트(스크림)를 깐다. 코드는 `engine.md`의 "사진" 절에 있다.
