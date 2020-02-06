# RNA

## pipeline_mrnaseq
Pipeline for mRNA-seq analysis.

To be run after fastq files have been trimmed with cgat-flow readqc, runs standard mRNA-seq analysis and QC.

#### Tasks
1) mapping
    - map reads with STAR and index BAM files
   - if mapping is conducted with CGAT pipeline, these BAMs can be used as input, rather than running STAR
2) readcounts
    - count reads over genes with featureCounts
3) summarystats
   - collect mapping statistics with picard tools
4) readquant
    - calculate TPMs with Salmon
5) coverage
    - generate bigWig coverage tracks for visualisation


#### Inputs:
* fastq.gz formatted files. Can be paired or single end.
* should be named sample_r1.fastq.[1-2].gz (PE) or sample_r1.fastq.gz (SE)
* naming convention: sample names should be informative e.g. "group_condition_treatment_replicate.fastq.1.gz" as they're used to 
generate a sample information table to annotate plots and create comparisons for DESeq2
* fastq files should be placed in a folder named "data.dir/"
* alternatively BAMs can be placed in "bam.dir/" and only tasks after mapping will be run

#### Outputs:
* bam.dir: mapped reads, bigWigs
* read_counts.dir: raw read counts
* salmon.dir: TPMs
* csvdb: sqlite3 db containing all QC metrics, raw read counts, TPMs, etc.
* Jupyter notebook reports: QC and DESeq2 analysis


## Requirements

#### Python
* cgat-core, cgat-flow, cgat-apps (https://github.com/cgat-developers)
* ruffus 2.8.3
* jupyter-notebook 6.0.2
* rpy2 3.2.4
* pandas 0.25.3
* numpy 1.17.3
* pybedtools 0.8.0
* seaborn 0.9.0
* matplotlib 3.1.1
* sqlite3
* yaml
* glob
* os
* re

#### Tools
* Salmon 0.11.3
* STAR 2.5.1b
* picard tools 2.10.9
* samtools 1.9
* subread 1.6.3
* deeptools 3.7.3

#### R
* ggplot2
* gplots
* gridExtra
* scales
* ggrepel
* wesanderson
* reshape2
* dplyr
* plyr
* grid
* RColorBrewer
* ComplexHeatmap
* circlize
* dendextend
* Rtsne
* DESeq2
* vsn
* topGO
* stringr

    
