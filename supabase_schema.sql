-- PharmAuto Supabase 스키마
-- Supabase 대시보드 > SQL Editor 에서 실행

-- ══════════════ 1. 약품 정보 ══════════════

CREATE TABLE drugs (
    insurance_code TEXT PRIMARY KEY,
    drug_name      TEXT NOT NULL,
    spec           TEXT DEFAULT '',
    short_name     TEXT DEFAULT '',
    report_count   INTEGER DEFAULT 1,
    updated_at     TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_drugs_name ON drugs (drug_name);

-- ══════════════ 2. 약품 규격 (도매상별) ══════════════

CREATE TABLE drug_units (
    insurance_code    TEXT NOT NULL,
    wholesaler_domain TEXT NOT NULL,
    pack_sizes        INTEGER[] NOT NULL,
    report_count      INTEGER DEFAULT 1,
    updated_at        TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (insurance_code, wholesaler_domain)
);

CREATE INDEX idx_drug_units_code ON drug_units (insurance_code);

-- ══════════════ 3. 도매상 셀렉터 ══════════════

CREATE TABLE wholesaler_selectors (
    domain          TEXT PRIMARY KEY,
    name            TEXT DEFAULT '',
    login_sel       JSONB DEFAULT '{}',
    search_sel      JSONB DEFAULT '{}',
    table_sel       JSONB DEFAULT '{}',
    confirm_sel     JSONB DEFAULT '{}',
    auto_detected   BOOLEAN DEFAULT false,
    verified_count  INTEGER DEFAULT 1,
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- ══════════════ 4. RLS (Row Level Security) ══════════════

ALTER TABLE drugs ENABLE ROW LEVEL SECURITY;
ALTER TABLE drug_units ENABLE ROW LEVEL SECURITY;
ALTER TABLE wholesaler_selectors ENABLE ROW LEVEL SECURITY;

-- 누구나 읽기 가능
CREATE POLICY "drugs_read" ON drugs FOR SELECT USING (true);
CREATE POLICY "drug_units_read" ON drug_units FOR SELECT USING (true);
CREATE POLICY "selectors_read" ON wholesaler_selectors FOR SELECT USING (true);

-- anon key로 쓰기 가능 (앱에서 데이터 기여)
CREATE POLICY "drugs_write" ON drugs FOR INSERT WITH CHECK (true);
CREATE POLICY "drugs_update" ON drugs FOR UPDATE USING (true);
CREATE POLICY "drug_units_write" ON drug_units FOR INSERT WITH CHECK (true);
CREATE POLICY "drug_units_update" ON drug_units FOR UPDATE USING (true);
CREATE POLICY "selectors_write" ON wholesaler_selectors FOR INSERT WITH CHECK (true);
CREATE POLICY "selectors_update" ON wholesaler_selectors FOR UPDATE USING (true);
