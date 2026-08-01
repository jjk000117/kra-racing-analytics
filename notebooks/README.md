# Jupyter Notebooks

Notebook은 탐색, 분석, 표·차트 작성과 결과 검증에 사용한다. 공식 수집·변환 로직은
`src/`와 `sql/`에서 관리한다.

프로젝트 루트에서 JupyterLab을 실행한다.

```powershell
C:\Users\jjk00\anaconda3\Scripts\conda.exe run -n kra-racing-analytics jupyter lab
```

## Notebook 목록

- `02c_raw_data_profiling.ipynb`: Raw 수집 결과 프로파일링
- `05d_market_structure_analysis.ipynb`: 월·경마장·등급·승식별 시장 구조 분석

5D Notebook의 원천 집계 SQL은 `sql/analysis/`에서 관리하며, Notebook 생성기는
`scripts/build_market_structure_notebook.py`다.
