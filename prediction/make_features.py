import time, pandas as pd, features
t=time.time()
g=pd.read_parquet('games.parquet')
f=features.compute(g)
out=pd.concat([g,f],axis=1)
out.to_parquet('features.parquet',index=False)
print(out.shape, time.time()-t)
