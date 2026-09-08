# Nextflow 26 (v2 parser) vs old pipelines — fixes and approach

## What is happening

Nextflow ≥ 26.04 parses `*.config` files with a strict v2 parser by default. Pipelines generated for Nextflow ≤ 25 (e.g. Viash-built openpipeline 2.1.1) commonly contain config syntax the v2 parser rejects, so the run dies during **config parsing**, before any real work starts:

| Error you see | Cause | Fix |
|---|---|---|
| `` `tempDir` is not defined `` at `docker/podman/charliecloud.temp = tempDir` | `tempDir` was defined via blocked Java (`java.nio.file.Paths.get(...)`), so the definition fails and every use is undefined | Replace definition with `tempDir = 'auto'`; bare `= tempDir` → `= 'auto'` |
| `Unexpected input: '('` at `def get_memory(to_compare) {` | Config files cannot define methods under v2 | Move the function out of `*.config` (into the workflow/module) |
| `` `SOME_VAR` is not defined `` at `key = "$SOME_VAR"` | Raw `$VAR` interpolation is gone | `key = "${env('SOME_VAR')}"` |
| `Invalid include source` at `includeConfig 'https://...'` | Remote includes are rejected | Vendor the file, include by local path |
| `Unexpected input: ':'` at `withName: 'A:B:C'` | Stricter selector quoting | Quote/escape per the v2 migration notes |

`'auto'` is a documented value for `docker/podman/charliecloud.temp` (a fresh tmp dir per container), so it is safe on old and new Nextflow.

>Colima/Docker is unrelated to these parse errors. It only matters afterwards: `docker ps` must work and the run needs Docker enabled (`-profile docker` or `docker.enabled = true`).


## Patch script

`nxf26_config_check.py` checks Nextflow `.config` files for syntax errors that may need updating for Nextflow 26 or later. The code searches every supplied directory and its subdirectories. If you do not supply a directory, it searches both the current directory and `~/.nextflow/assets`, where Nextflow stores downloaded pipelines.

```bash
# Check the current directory and the Nextflow asset cache:
python3 nxf26_config_check.py

# Check a specific pipeline directory:
python3 nxf26_config_check.py /path/to/pipeline

# Apply the automatic fixes in a specific pipeline directory:
python3 nxf26_config_check.py --fix /path/to/pipeline
```

- Use the `--fix` option to bulk edit the files
- Use without the fix for just a diagnostic

For now it takes care of the following errors:

1. Error with `tempDir = java.nio.file.Paths.get(...)` replaced by `tempDir = 'auto'`.
2. Error with `<container> = tempDir` replace by  `<container> = 'auto'`

>For container temporary-directory settings, `'auto'` tells Nextflow to create a separate temporary directory for each container.

Before changing a configuration file, the script saves the original beside it with `.bak` added to the filename. For example, `nextflow.config` is backed up as `nextflow.config.bak`. An existing backup with the same name is overwritten.

## Quick patch (it is for us)

Run the patch with the python script. It is possible that other error come from other pipelines. Just add the regex pattern and add a function for the fix. If the fix module becomes too big we can consider modularizing it but right now it is fine.

Once patches are applied use the following command:

```bash
NXF_SYNTAX_PARSER=v1 nextflow run <pipeline> <options>
```

>you can also add `export=NXF_SYNTAX_PARSER=v1` to your `.bashrc` or `zshrc`

>TO TEST: Can we [pin](https://nf-co.re/docs/get_started/environment_setup/nextflow) a secific version of nextflow ? i.e `NXF_VER=25.10.5`
```

## Customise your configuration (after parsing checks passes)

I got the following errors:

```text
Process requirement exceeds available CPUs -- req: 20; avail: 18
```

```text
ModuleNotFoundError: No module named 'yaml'
```

best is to override it with your own config file. Do not touch the pipeline.

I created `my_resources.config` in the dir.

>name the file the way you want

Then to fix the CPU one:

```groovy
process {
  withName: 'build_bdrhap_reference_process' {
    cpus = 16
  }
}
```

Then to fix the module error just enable the docker or other container backend.

```groovy
docker.enabled = true

process {
  withName: 'build_bdrhap_reference_process' {
    cpus = 16
    memory = 32.GB \\ put the memory you want
  }
}
```

Then run the pipeline with:

```bash
NXF_SYNTAX_PARSER=v1 nextflow run <pipeline> <options> -c my_resources.config
```

AGENT_CHECK
**1. `main.nf` — thin Viash wrapper, no biology.** It defines one real process (`build_bdrhap_reference_process`, labeled `highmem, highcpu`, container `bdgenomics/rhapsody:2.2.1`) plus the standard publish steps that copy the tarball to your `--publish_dir`. All it does is stage your FASTA/GTF and run `script.py` inside the container.

**2. `script.py` — translator, no biology.** It validates inputs, absolutizes paths, writes a CWL job file (`config.yml`) mapping your flags to CWL inputs (including `Maximum_threads` = the Nextflow CPUs — that's how your 16 got through), then shells out to `cwl-runner --no-container … make_rhap_reference_2.2.1_nodocker.cwl config.yml` and moves the resulting `Rhap_reference.tar.gz` to your output path. This is the file that needed `yaml` — hence your earlier `ModuleNotFoundError` when Docker was off.

**3. `run_reference_generator.sh` — the real work, inside BD's image.** From your log's trace (this script ships in the container, not the repo): preprocess GTF → `STAR genomeGenerate` → `bwa-mem2 index` → pack everything into the tarball. Your log walked exactly this path.

**4. Rhapsody-specific preparation — yes, several things**, all from the verified component docs:

- **GTF filtering** by `gene_type`/`gene_biotype` (protein_coding, lncRNA, IG/TR V/D/J/C genes…) unless `--filtering_off`; your log's `...-processed.gtf` is this step's output.
- **GTF contract**: `gene_name`/`gene_id` on gene and exon features, exons matched to genes, TR/IG biotypes required for VDJ assays.
- **Mitochondrial contigs** declared (`chrM;chrMT;M;MT` — matches your Ensembl `MT`), used downstream to flag nuclear fragments in ATAC.
- **WTA-only vs WTA+ATAC** index flavors (`--wta_only_index`).
- **Extra sequences** (phiX spike-in, transgenes) with auto-generated GTF lines merged in.
- **Archive layout**: the tarball bundles STAR index + processed GTF (+ bwa-mem2 index) in exactly the shape the BD mapping pipeline consumes.
1. **The interface — openpipeline repo** (`src/reference/build_bdrhap_reference/`): `config.vsh.yaml` declares the Rhapsody-specific parameters (mitochondrial contigs, GTF filtering rules, WTA-only flag, extra sequences) and the `.cwl` file — which is BD-authored, just vendored there — specifies the tool's inputs/outputs. `script.py` itself is generic plumbing with zero Rhapsody logic.
2. **The implementation — BD's Docker image** (`bdgenomics/rhapsody:2.2.1`): the actual filtering code and archive packing live in `run_reference_generator.sh` *inside* that image. It's not in any git repo you can browse.
