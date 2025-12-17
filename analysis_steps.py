import os
import json
import pandas as pd
import numpy as np
import unicodedata

ROOT = '.'
YEARS = [str(y) for y in range(2009, 2024)]

# helpers

def _normalize(s):
    if not isinstance(s, str):
        return ''
    nk = unicodedata.normalize('NFKD', s)
    return ''.join(c for c in nk if not unicodedata.combining(c)).strip().lower()


def find_country_col(df):
    for c in df.columns:
        n = _normalize(c)
        if n in {'pais', 'pais', 'country'} or 'pais' in n or 'country' in n or 'pa' in n:
            return c
    # fallback common names
    for k in ['País', 'Pais', 'pais', 'country', 'Country']:
        if k in df.columns:
            return k
    return None


def safe_numeric(s):
    return pd.to_numeric(s.astype(str).str.replace('.', '').str.replace(',', '.'), errors='coerce')

# 1) Data quality report
files_to_check = [
    'comercializacao_filtrada.csv', 'Comercializacao.csv',
    'exportacao_qtd.csv', 'exportacao_valor.csv',
    'importacao_qtd.csv', 'importacao_valor.csv',
    'producao_filtrada.csv', 'processamento_filtrado.csv'
]

dq_rows = []
for fname in files_to_check:
    fpath = os.path.join(ROOT, fname)
    if not os.path.exists(fpath):
        continue
    # tentar ler com separador ';' (formato usado no notebook), depois tentar latin1, por fim tentar autodetect
    try:
        df = pd.read_csv(fpath, dtype=str, sep=';')
    except Exception:
        try:
            df = pd.read_csv(fpath, encoding='latin1', dtype=str, sep=';')
        except Exception:
            # última tentativa: engine python com sep None para autodetect
            df = pd.read_csv(fpath, dtype=str, engine='python', sep=None)
    info = {
        'file': fname,
        'rows': df.shape[0],
        'cols': df.shape[1],
        'duplicate_rows': int(df.duplicated().sum())
    }
    # per-column missing % and dtype
    col_stats = []
    for c in df.columns:
        vals = df[c]
        missing = int(vals.isna().sum() + (vals.astype(str).str.strip()=='').sum())
        uniq = vals.nunique(dropna=True)
        col_stats.append({'column': c, 'missing': missing, 'missing_pct': missing / max(1, df.shape[0]), 'unique': uniq})
    info['columns'] = col_stats
    dq_rows.append(info)

with open('data_quality_report.json', 'w', encoding='utf-8') as fh:
    json.dump(dq_rows, fh, ensure_ascii=False, indent=2)

# also save a tabular CSV summary (one row per file)
summary_rows = []
for info in dq_rows:
    summary_rows.append({'file': info['file'], 'rows': info['rows'], 'cols': info['cols'], 'duplicate_rows': info['duplicate_rows']})
pd.DataFrame(summary_rows).to_csv('data_quality_summary.csv', index=False)
print('Data quality report written: data_quality_report.json and data_quality_summary.csv')

# 2) CAGR for comercializacao (group by country)
cagr_rows = []
cfname = 'comercializacao_filtrada.csv' if os.path.exists('comercializacao_filtrada.csv') else ('Comercializacao.csv' if os.path.exists('Comercializacao.csv') else None)
if cfname:
    dfc = pd.read_csv(cfname, dtype=str)
    country_col = find_country_col(dfc)
    if country_col is None:
        print('Country column not found for comercializacao; skipping CAGR')
    else:
        # ensure year cols numeric
        for y in YEARS:
            if y in dfc.columns:
                dfc[y] = safe_numeric(dfc[y]).fillna(0)
        years_present = [y for y in YEARS if y in dfc.columns]
        if years_present:
            grp = dfc.groupby(country_col)[years_present].sum(numeric_only=True)
            for country, row in grp.iterrows():
                start = row[years_present[0]]
                end = row[years_present[-1]]
                if start > 0 and end >= 0:
                    n = len(years_present)-1
                    cagr = (end / start) ** (1.0 / n) - 1 if n>0 else np.nan
                else:
                    cagr = np.nan
                cagr_rows.append({'País': country, 'start_year': years_present[0], 'start_val': float(start), 'end_year': years_present[-1], 'end_val': float(end), 'CAGR': cagr})
            pd.DataFrame(cagr_rows).sort_values('CAGR', ascending=False).to_csv('cagr_comercializacao.csv', index=False)
            print('CAGR comercializacao saved to cagr_comercializacao.csv')
        else:
            print('No year columns present for comercializacao')
else:
    print('No comercializacao CSV found; skipping CAGR')

# 3) Price per liter for exportacao (valor / qtd)
price_rows = []
if os.path.exists('exportacao_qtd.csv') and os.path.exists('exportacao_valor.csv'):
    try:
        qtd = pd.read_csv('exportacao_qtd.csv', dtype=str, sep=';')
    except Exception:
        qtd = pd.read_csv('exportacao_qtd.csv', dtype=str, engine='python', sep=None)
    try:
        val = pd.read_csv('exportacao_valor.csv', dtype=str, sep=';')
    except Exception:
        val = pd.read_csv('exportacao_valor.csv', dtype=str, engine='python', sep=None)
    # try to find join keys (Id and País if present)
    join_keys = [k for k in ['Id','País','Pais','Country'] if k in qtd.columns and k in val.columns]
    if not join_keys:
        # fallback: merge on all non-year columns
        non_year_q = [c for c in qtd.columns if c not in YEARS]
        non_year_v = [c for c in val.columns if c not in YEARS]
        common = [c for c in non_year_q if c in non_year_v]
        join_keys = common
    if join_keys:
        merge_on = join_keys
        # convert year cols
        for y in YEARS:
            if y in qtd.columns:
                qtd[y] = safe_numeric(qtd[y]).fillna(0)
            if y in val.columns:
                val[y] = safe_numeric(val[y]).fillna(0)
        merged = pd.merge(qtd, val, on=merge_on, suffixes=('_qtd','_valor'))
        # compute price per liter per year
        for y in YEARS:
            yq = y
            yv = y
            if y in merged.columns and y in merged.columns:
                # both present as same name; use suffixed names by checking which exist
                col_q = y if (y in merged.columns and f'{y}_qtd' not in merged.columns and f'{y}_valor' not in merged.columns and y in qtd.columns) else (f'{y}_qtd' if f'{y}_qtd' in merged.columns else None)
                col_v = y if (y in merged.columns and f'{y}_qtd' not in merged.columns and f'{y}_valor' not in merged.columns and y in val.columns) else (f'{y}_valor' if f'{y}_valor' in merged.columns else None)
                if col_q and col_v:
                    merged[f'price_{y}'] = merged[col_v] / merged[col_q].replace({0: np.nan})
        # aggregate average price per country (if País in merge keys)
        country_key = None
        for k in ['País','Pais','country','Country']:
            if k in merged.columns:
                country_key = k
                break
        if country_key:
            price_by_country = {}
            for y in YEARS:
                col = f'price_{y}'
                if col in merged.columns:
                    avg = merged.groupby(country_key)[col].mean()
                    dfp = avg.reset_index().rename(columns={col: f'avg_price_{y}'})
                    if price_by_country == {}:
                        price_by_country = dfp
                    else:
                        price_by_country = price_by_country.merge(dfp, on=country_key, how='outer')
            if isinstance(price_by_country, dict):
                print('No price columns computed')
            else:
                price_by_country.to_csv('price_per_liter_exportacao.csv', index=False)
                print('Price per liter exportacao saved to price_per_liter_exportacao.csv')
        else:
            print('No country key found to aggregate prices')
    else:
        print('No join keys found between exportacao qtd and valor')
else:
    print('Exportacao qtd/valor CSVs not both present; skipping price per liter')

print('Analysis script finished.')
