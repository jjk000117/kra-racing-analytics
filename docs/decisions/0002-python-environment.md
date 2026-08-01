# ADR-0002: 기존 Anaconda에 프로젝트 전용 Conda 환경 사용

- 상태: Accepted
- 결정일: 2026-08-01

## 결정

기존 Anaconda 설치를 환경 관리자로 사용하고 `kra-racing-analytics`라는 프로젝트 전용 Conda 환경을 만든다.

- 환경 경로: `C:\Users\jjk00\anaconda3\envs\kra-racing-analytics`
- Python: 3.12 계열
- Jupyter: 전용 환경의 JupyterLab과 `python3` Kernel
- 공식 실행: `conda run -n kra-racing-analytics ...` 또는 전용 환경 활성화 후 CLI

기존 `base` 환경에는 프로젝트 패키지를 설치하지 않는다.

## 근거

- 사용자가 기존 Anaconda와 Jupyter 사용 경험이 있다.
- 일반 Python이나 별도 코드 편집기를 추가로 설치할 필요가 없다.
- 프로젝트 패키지와 기존 `base` 패키지를 분리할 수 있다.
- Codex가 공식 CLI와 테스트를 실행하고 사용자는 브라우저 JupyterLab에서 결과를 탐색할 수 있다.

## 실행 환경 복원

저장소 루트에서 다음 계약으로 환경을 재생성한다.

```powershell
C:\Users\jjk00\anaconda3\Scripts\conda.exe env create --file environment.yml
```

`pyproject.toml`이 런타임·개발 의존성의 공식 정의이며 `environment.yml`은 Conda 진입점이다.

## 제약

- Anaconda 설치 경로는 사용자마다 다를 수 있으므로 데이터 파이프라인 코드에 하드코딩하지 않는다.
- README의 절대 경로는 현재 Windows 환경을 위한 실행 예시다.
- Jupyter Notebook은 탐색과 검증에만 사용하고 공식 변환 로직은 `src/`와 `sql/`에 둔다.

