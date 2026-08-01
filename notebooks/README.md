# Jupyter notebooks

노트북은 탐색, 샘플 대조, 품질 검사와 지표 검증에만 사용한다. 공식 수집·변환 로직은 `src/`와 `sql/`에 둔다.

프로젝트 루트에서 브라우저 JupyterLab을 실행한다.

```powershell
C:\Users\jjk00\anaconda3\Scripts\conda.exe run -n kra-racing-analytics jupyter lab
```

노트북에서는 프로젝트 연결 함수를 사용한다.

```python
from kra_analytics.database import connect_database

with connect_database(read_only=True) as connection:
    display(connection.sql("SELECT schema_name FROM information_schema.schemata").df())
```

