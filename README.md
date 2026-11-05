# Flexcil Cloud Export & Automated PDF Sync Pipeline

Flexcil Export는 태블릿 필기 앱인 Flexcil의 독자적 바이너리 형식(`.flx`)을 클라우드(Google Drive)에서 비동기로 수집하여, 고품질 벡터 PDF로 자동 변환하고 사설 NAS로 실시간 동기화하는 **서버리스형 자동화 파이프라인**입니다.

---

## 1. 프로젝트 개요 (Overview)

- **배경**: 모바일 태블릿(Galaxy Tab 등)에서 작성된 필기 문서는 Flexcil 전용 확장자(`.flx`)로 저장되어 데스크톱 PC나 타 기기에서 직접 열람하기 어렵고, 수동 PDF 내보내기는 번거로운 문제가 존재
- **해결책**:
  1. 태블릿이 구글 드라이브로 자동 백업한 `.flx` 파일을 Linux 서버가 10분 주기로 자동 감지
  2. 내용이 변경된 문서만 선별(Delta-only)하여 서버에서 백그라운드로 PDF 렌더링
  3. 사설 NAS의 읽기 전용 공유 폴더(`mknas/Flexcil`)에 태블릿과 동일한 디렉토리 계층 구조로 즉시 배포
  4. 이전 버전과 원본 파일은 이력 폴더에 안전하게 보존

---

## 2. 시스템 아키텍처 (Architecture)

```
[Tablet: Flexcil App] ──(Auto Sync)──► [Google Drive: "Flexcil Sync"]
                                                     │
                                                     │ (rclone: GCP Service Account)
                                                     ▼
                                        [nas-server (Ubuntu)]
                                                     │
                      ┌──────────────────────────────┴──────────────────────────────┐
                      ▼                                                             ▼
           [Delta Detector (Hash)]                                       [FLX Extraction Engine]
           - documents.list 분석                                          - Zip archive unpack
           - 변경되지 않은 파일 건너뜀                                    - Vector PDF page rendering
                      │                                                             │
                      └──────────────────────────────┬──────────────────────────────┘
                                                     ▼
                                         [Sync & Storage Layer]
                                         - /srv/nas/Flexcil/ (열람용 PDF)
                                         - /srv/nas/Flexcil_백업/ (원본 .flx 사본)
                                         - _마지막동기화.txt (상태 리포트)
```

---

## 3. 핵심 기술 스택 (Tech Stack)

| 영역 | 기술 스택 | 설명 |
|---|---|---|
| **Language & Core** | Python 3.10+, Bash | 문서 파싱 및 자동화 스크립트 |
| **PDF Rendering** | PyMuPDF (`pymupdf`) | 고해상도 벡터 필기 선 및 주석 렌더링 |
| **Cloud Storage Client** | rclone | 구글 드라이브 서비스 계정(`service_account.json`) 헤드리스 연동 |
| **Storage & Sharing** | Samba (CIFS), Linux POSIX | NAS 공유 폴더 사용자 권한(`mknas:mknas`) 일치화 |
| **Automation** | Linux Cron, Flock | 10분 주기 단일 인스턴스 락 스케줄링 |

---

## 4. 파일 구성 (Structure)

```
flexcil-export/
├── flx2pdf.py        # .flx 바이너리 아카이브 파서 및 PDF 벡터 렌더러
├── sync_export.py    # documents.list 기반 변경 문서 감지 및 차분 변환기
├── flexcil-sync.sh   # 전체 rclone 수집 → 변환 → NAS 배포 오케스트레이션 셸
└── requirements.txt
```

---

## 5. 엔지니어링 특징 (Engineering Highlights)

1. **초경량 저사양 서버 최적화**:
   - 1GB RAM의 오라클 프리티어 인스턴스 환경에서 메모리 부하를 최소화하기 위해 문서 전체를 일괄 변환하지 않고, SHA-256 해시 및 수정 시각을 비교하여 변경된 파일만 스트리밍 방식으로 변환
2. **서비스 계정(Service Account) 보안 격리**:
   - 개인 구글 계정 전체 권한이 아닌, 특정 `Flexcil Sync` 폴더만 뷰어로 공유받은 전용 GCP 서비스 계정 키를 사용하여 보안 사고 방지
3. **무중단 멱등성(Idempotency) 보장**:
   - 네트워크 오류나 프로세스 강제 중단 시에도 파일 깨짐이 없도록 임시 디렉토리에서 변환 완료 후 원자적 교체(Atomic Move) 수행
