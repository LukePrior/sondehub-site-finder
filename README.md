# sondehub-site-finder
Script that uses reverse flight predictions to find likely undefined radiosonde launch sites - 6841

## Fetching reverse predictions

This data is stored in the SondeHub OpenSearch cluster.

```
elasticdump --input https://es.v2.sondehub.org:443/reverse-prediction-*/_search --output reverse-prediction-index.json --type=data --size=100
```