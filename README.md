# Pig genome reference and BD Rhapsody analysis

This directory contains the files and commands needed to prepare a pig genome reference and analyse BD Rhapsody sequencing data with [OpenPipelines](https://openpipelines.bio/). The workflow has two stages: build the reference once, then use that archive to process sequencing reads.

## Installation

### Java with SDKMAN

Nextflow requires Java 17 or later. Install an LTS release such as Temurin 17 with [SDKMAN](https://sdkman.io/):

```bash
curl -s "https://get.sdkman.io" | bash
source "$HOME/.sdkman/bin/sdkman-init.sh"

# Find the current Temurin 17 identifier, then install it.
sdk list java
sdk install java 17.0.20-tem

java -version
```

If that exact identifier is no longer listed, use the current Temurin 17 identifier shown by `sdk list java`.

### Nextflow

Install [Nextflow](https://www.nextflow.io/docs/latest/install.html) and place it on your `PATH`:

```bash
curl -s https://get.nextflow.io | bash
chmod +x nextflow
mkdir -p "$HOME/.local/bin"
mv nextflow "$HOME/.local/bin/"
export PATH="$HOME/.local/bin:$PATH"

nextflow info
```

Add the `PATH` export to `~/.zshrc` or `~/.bashrc` to keep it available in new terminal sessions.

### Docker

Install [Docker](https://docs.docker.com/get-docker/), start the Docker service, and check that it works:

```bash
docker ps
```

Docker Desktop is the simplest option on macOS. Colima can also provide the Docker runtime. OpenPipelines additionally supports Podman and Singularity/Apptainer, but the commands below use Docker.

## Pipeline 1 — Build the BD Rhapsody pig reference

The [reference builder](https://openpipelines.bio/components/modules/reference/build_bdrhap_reference.html) converts the Ensembl genome FASTA and GTF annotation into the archive required by the mapping pipeline.

1. **Read the genome files.** The component receives the compressed FASTA sequence and GTF annotation.
2. **Prepare the annotation.** By default, it keeps the supported `gene_type`/`gene_biotype` entries. The GTF must use matching `gene_name` or `gene_id` attributes on gene and exon records. Extra sequences such as transgenes can also be added.
3. **Build the indexes.** STAR builds the genome index used for RNA alignment. The default WTA + ATAC reference also includes a `bwa-mem2` index; use `--wta_only_index` when ATAC analysis is not needed.
4. **Create the archive.** The indexes and processed GTF are packed into one compressed reference archive for Pipeline 2.

The mitochondrial contig defaults include `MT`, which matches the Ensembl pig files in this directory.

## Pipeline 2 — Map and count BD Rhapsody reads

The [BD Rhapsody mapping component](https://openpipelines.bio/components/modules/mapping/bd_rhapsody.html) runs the BD Rhapsody Sequence Analysis Pipeline 2.2.1 on assay FASTQ files.

1. **Check the inputs and assay settings.** The pipeline reads WTA, Targeted mRNA, AbSeq, multiplexing, VDJ, and/or ATAC inputs when supplied.
2. **Prepare the reads.** It performs quality filtering and extracts the cell-label and UMI information.
3. **Align the reads.** RNA reads use STAR; ATAC reads use `bwa-mem2` when ATAC data are provided.
4. **Count molecules and call cells.** Molecules are annotated before putative cells are selected. WTA mRNA uses RSEC correction; DBEC is used for Targeted mRNA and AbSeq.
5. **Write the results.** The pipeline produces count matrices and quality reports. Seurat, MuData, BAM, multiplexing, VDJ, and ATAC outputs are optional and depend on the supplied assay data and options.

The documented VDJ presets are human- and mouse-specific. Do not assume that they support pig VDJ annotations without separate validation.

### Containers and wrappers

Both components use the same arrangement, so it is described only once here:

| Pipeline | Container launched by Nextflow |
|---|---|
| Reference builder | `ghcr.io/openpipelines-bio/openpipeline/reference/build_bdrhap_reference:2.1.0` |
| Mapping and counting | `ghcr.io/openpipelines-bio/openpipeline/mapping/bd_rhapsody:2.1.0` |

The `2.1.0` companion tags shown above are the images referenced by OpenPipelines release `2.1.1`. These containers are generated with Viash from the BD image [`bdgenomics/rhapsody:2.2.1`](https://hub.docker.com/r/bdgenomics/rhapsody/tags). Inside the container, a Python wrapper translates the Nextflow parameters into a CWL job and starts the bundled BD workflow. The inner `cwl-runner --no-container` option avoids starting another container; the outer task still runs in Docker.

## Usage

Run these commands from this directory. OpenPipelines is pinned to release `2.1.1`, and `NXF_SYNTAX_PARSER=v1` keeps this older generated pipeline compatible with newer Nextflow installations.

### 1. Build the reference

```bash
NXF_SYNTAX_PARSER=v1 nextflow run openpipelines-bio/openpipeline \
  -r 2.1.1 \
  -profile docker \
  -main-script target/nextflow/reference/build_bdrhap_reference/main.nf \
  --genome_fasta Sus_scrofa.Sscrofa11.1.dna.toplevel.fa.gz \
  --gtf Sus_scrofa.Sscrofa11.1.116.gtf.gz \
  --reference_archive pig_rhapsody_reference.tar.gz \
  --publish_dir reference_output/ \
  -c my_resources.config
```

This publishes `reference_output/pig_rhapsody_reference.tar.gz`. The local `my_resources.config` enables Docker and limits the reference-building process to 16 CPUs. Make sure Docker has enough memory and CPUs for genome indexing.

Add `--wta_only_index` to the command only if the reference will not be used for ATAC data.

### 2. Map and count WTA reads

This is a WTA example. Replace the example FASTQ paths and run name with the files for the experiment:

```bash
NXF_SYNTAX_PARSER=v1 nextflow run openpipelines-bio/openpipeline \
  -r 2.1.1 \
  -profile docker \
  -main-script target/nextflow/mapping/bd_rhapsody/main.nf \
  --reads 'data/sample_R1.fastq.gz;data/sample_R2.fastq.gz' \
  --reference_archive reference_output/pig_rhapsody_reference.tar.gz \
  --run_name pig-sample \
  --output_dir sample_output \
  --publish_dir rhapsody_output/
```

For ATAC data, use the component documentation to add `--reads_atac` with its R1, R2, and I2 files. Add assay-specific references and options only when they apply to the experiment. Review the mapping process resources separately: `my_resources.config` currently changes only the reference builder.

## Nextflow compatibility and troubleshooting

See [`PATCH.md`](PATCH.md) for the Nextflow parser issue, the local configuration checker, resource overrides, and container troubleshooting. Do not edit generated files in `work/` or cached pipeline files as a permanent fix.

## Reference genome downloads

Download the matching input files from Ensembl release 116:

- [Pig genome FASTA — `Sus_scrofa.Sscrofa11.1.dna.toplevel.fa.gz`](https://ftp.ensembl.org/pub/release-116/fasta/sus_scrofa/dna/Sus_scrofa.Sscrofa11.1.dna.toplevel.fa.gz)
- [Pig GTF annotation — `Sus_scrofa.Sscrofa11.1.116.gtf.gz`](https://ftp.ensembl.org/pub/release-116/gtf/sus_scrofa/Sus_scrofa.Sscrofa11.1.116.gtf.gz)

Keep the FASTA and GTF from the same assembly and Ensembl release.

## Author

Faouzi Braza
