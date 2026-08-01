# Mart SQL

사업성 분석용 Star Schema와 Mart는 다음 파일에서 관리한다.

- DDL과 기준정보: `sql/ddl/006_create_star_schema.sql`
- 전체 재구축 변환: `sql/transforms/002_build_star_schema.sql`
- 상세 설계: `docs/star-schema-design.md`
- 구축 및 검증 결과: `docs/star-schema-build.md`

분석 객체는 DuckDB의 `analytics` 스키마에 생성한다. Canonical은 입력 원천으로만 읽으며
Star 재구축 과정에서 수정하지 않는다.
