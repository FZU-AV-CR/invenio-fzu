# Local installation

## Check prerequisites

```bash
./run.sh cli check-requirements -d
```

## Install the instance

```bash
./run.sh reset
```

## Create a bucket inside MinIO

1. Head to http://localhost:9001
2. Login with access key `aa-physica-aa` and secret key `aaa-physica-aaa`
3. Create a bucket named `default`

## Run the instance

```bash
./run.sh run
``` 

The instance will be available at https://localhost:5000

## Get the token and store it

```bash

# if resetting already existing instance
uvx nrp-cmd remove repository physica-local || true

# add the local repository. Will open browser page to get the token, 
# paste it in the terminal when prompted
uvx nrp-cmd add repository  --no-verify-tls  https://127.0.0.1:5000/ physica-local
```

## Upload sample data

```bash
cd sample_data
./upload_sample_data.sh
```
