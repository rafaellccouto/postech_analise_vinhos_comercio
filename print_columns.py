import pandas as pd

for sep in [';',',','\t']:
    try:
        df = pd.read_csv('comercializacao_filtrada.csv', sep=sep, nrows=0)
        print('sep=',sep,'->', list(df.columns))
        break
    except Exception as e:
        print('sep=',sep,'failed:', e)
