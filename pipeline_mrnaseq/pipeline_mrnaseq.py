"""===========================
Pipeline mRNA-seq
===========================

:Author: Tariq Khoyratty
:Release: $Id$
:Date: |today|
:Tags: Python

Overview
========

This pipeline is for the processing of mapped mRNA-seq reads.
Reads in Ensembl protein coding genes are counted with featureCounts,
& quantified with Salmon. Raw counts are also reported for 
differential expression analysis. Picard tools is used to collect
QC metrics.

Usage
=====

See :ref:`PipelineSettingUp` and :ref:`PipelineRunning` on general
information how to use CGAT pipelines.

Configuration
-------------

The pipeline requires a configured :file:`pipeline.ini` file.
CGATReport report requires a :file:`conf.py` and optionally a
:file:`cgatreport.ini` file (see :ref:`PipelineReporting`).

Default configuration files can be generated by executing:

   python <srcdir>/pipeline_mrnaseq.py config

Input files
-----------

Bam files of mapped reads. Filename should be of the following format:

condition_time_replicate.bam


Requirements
------------


Pipeline output
===============

Raw counts of reads in genes, and normalised counts from Salmon

Glossary
========

.. glossary::


Code
====

"""
from ruffus import *

import sys
import os
import glob
import sqlite3
import cgatcore.experiment as E
from cgatcore import pipeline as P
from cgat.BamTools import bamtools as BamTools
import pandas as pd
import re

# initialize pipeline
P.initialize()

# Pipeline configuration
P.get_parameters(
		 ["%s/pipeline.yml" % os.path.splitext(__file__)[0],
		  "../pipeline.yml",
		  "pipeline.yml"],
		 )

PARAMS = P.PARAMS

db = PARAMS['database']['url'].split('./')[1]

def connect():
    '''connect to database.
    This method also attaches to helper databases.
    '''

    dbh = sqlite3.connect(db)

    if not os.path.exists(PARAMS["annotations_database"]):
        raise ValueError(
                     "can't find database '%s'" %
                     PARAMS["annotations_database"])

    statement = '''ATTACH DATABASE '%s' as annotations''' % \
    (PARAMS["annotations_database"])

    cc = dbh.cursor()
    cc.execute(statement)
    cc.close()

    return dbh


# utility functions

def isPaired(files):
    '''Check whether input files are single or paired end
       Note: this is dependent on files having correct suffix'''
    
    paired = []

    for fastq in files:
        Fpair = re.findall(".*.fastq.1.gz", fastq)
        paired = paired + Fpair

    if len(paired)==0:
        unpaired = True

    else:
        unpaired = False
    
    return unpaired

# ---------------------------------------------------
# Specific pipeline tasks

# Configure pipeline for paired or single end data
Unpaired = isPaired(glob.glob("data.dir/*fastq*gz"))

# and strandedness
Stranded = bool(PARAMS["strandedness"])

# were reads mapped using CGAT pipelines?
cgat_mapping = bool(PARAMS["cgat_mapping_bool"])


#####################################################
#################### Mapping ########################
#####################################################
@follows(connect)
@files(None, "sample_info.txt")
def makeSampleInfoTable(infile, outfile):
    '''Parse sample names and construct sample info table,
       with "category" column for DESeq2 design'''
    
    make_sample_table = True
    info = {}

    files = glob.glob("data.dir/*fastq*gz")
    
    if len(files)==0:
        pass
    
    for f in files:
        sample_id = os.path.basename(f).split(".")[0]
        attr =  os.path.basename(f).split(".")[0].split("_")

        if len(attr) == 2:
            cols = ["sample_id", "condition", "replicate"]

        elif len(attr) == 3:
            cols = ["sample_id", "condition", "treatment", "replicate"]

        elif len(attr) == 4:
            cols = ["sample_id", "group", "condition", "treatment", "replicate"]

        else:
            make_sample_table = False
            print("Please reformat sample names according to pipeline documentation")

        if sample_id not in info:
            info[sample_id] = [sample_id] + attr

    if make_sample_table:
        sample_info = pd.DataFrame.from_dict(info, orient="index")
        sample_info.columns = cols
        sub = [x for x in list(sample_info) if x not in ["sample_id", "index", "replicate"]]
        sample_info["category"] = sample_info[sub].apply(lambda x: '_'.join(str(y) for y in x), axis=1)
        sample_info.reset_index(inplace=True, drop=True)
        
        con = sqlite3.connect(db)
        sample_info.to_sql("sample_info", con, if_exists="replace")

        sample_info.to_csv(outfile, sep="\t", header=True, index=False)


@follows(makeSampleInfoTable, mkdir("star.dir"))
@follows(mkdir("star.dir"))
@active_if(Unpaired==False)
@transform("data.dir/*.fastq.1.gz",
           regex(r"data.dir/(.*).fastq.1.gz"),
           r"star.dir/\1.bam")
def starMapping(infile, outfile):

    genomeDir = PARAMS["star_index_dir"]

    tmpdir = PARAMS["tmp_dir"]
    
    log_prefix = outfile.rstrip(".bam") + "."

    read1 = infile
    read2 = read1.replace(".fastq.1.gz", ".fastq.2.gz")
    
    statement = f'''tmp=`mktemp -p {tmpdir}` &&
                    STAR 
                      --runMode alignReads 
                      --runThreadN 12 
                      --genomeDir {genomeDir}
                      --outSAMstrandField intronMotif 
                      --outFileNamePrefix {log_prefix}
                      --outStd SAM 
                      --outSAMunmapped Within 
                      --outFilterMismatchNmax 2 
                      --readFilesIn {read1} {read2}
                      --readFilesCommand zcat | samtools view -b - 
                      >  $tmp &&
                    samtools sort -O BAM  $tmp > {outfile} &&
                    rm $tmp'''

    P.run(statement, job_threads=12)

    
@active_if(Unpaired)
@transform("data.dir/*.fastq.gz",
           regex(r"data.dir/(.*).fastq.gz"),
           r"star.dir/\1.bam")
def starMapping_SE(infile, outfile):

    genomeDir = PARAMS["star_index_dir"]

    tmpdir = PARAMS["tmp_dir"]

    log_prefix = outfile.rstrip(".bam") + "."
    
    statement = f'''tmp=`mktemp -p {tmpdir}` &&
                    STAR 
                      --runMode alignReads 
                      --runThreadN 12 
                      --genomeDir {genomeDir}
                      --outSAMstrandField intronMotif 
                      --outFileNamePrefix {log_prefix}
                      --outStd SAM 
                      --outSAMunmapped Within 
                      --outFilterMismatchNmax 2 
                      --readFilesIn {infile} 
                      --readFilesCommand zcat | samtools view -b - 
                      >  $tmp &&
                    samtools sort -O BAM  $tmp > {outfile} &&
                    rm $tmp''' 

    P.run(statement, job_threads=12)
    

@follows(starMapping, starMapping_SE)
@transform("star.dir/*.bam", suffix(r".bam"), r".bam.bai")
def indexBam(infile, outfile):

    statement = f'''samtools index -b {infile} {outfile}'''

    P.run(statement)

    
@follows(indexBam, mkdir("bam.dir"))
@transform("star.dir/*.bam",
           regex(r"star.dir/(.*).bam"),
           r"bam.dir/\1.bam")
def addPseudoSequenceQuality(infile, outfile):
    '''to allow multiQC to pick up the picard metric files
    sequence quality needs to be added if it is stripped.
    Therefore an intermediate sam file needs to be generated
    Arguments
    ---------
    infile : string
    Input file in :term:`BAM` format.
    outfile : string
    Output file in :term: `BAM` format.
    '''

    log = outfile.replace(".bam", ".bam2bam.log")
    
    if cgat_mapping:
        venv = PARAMS["cgat_mapping_venv"]
        
        statement = f'''cat {infile} | 
                          cgat bam2bam 
                            -v 5
                            --method=set-sequence 
                            --log={log}
                            > {outfile}'''
        
        P.run(statement, job_condaenv=venv)

        statement = f'''samtools index {outfile}'''

        P.run(statement)

    else:
        # if CGAT pipelines not used symlink data into new dir
        in_index = infile.replace(".bam", ".bam.bai")
        out_index = outfile.replace(".bam", ".bam.bai")

        statement = f'''dir=`pwd` &&
                        ln -s $dir/{infile} {outfile} &&
                        ln -s $dir/{in_index} {out_index}'''

        P.run(statement)
    

@follows(indexBam, addPseudoSequenceQuality)
def mapping():
    pass
    
#####################################################
################## Raw counts #######################
#####################################################
@follows(mapping, mkdir("read_counts.dir"))
@merge("bam.dir/*.bam", "read_counts.dir/featureCounts.txt")
def featureCount(infiles, outfile):
    '''Count reads falling in ensembl genes (including introns)'''

    gtf = os.path.join(PARAMS["annotations_dir"], PARAMS["annotations_ensembl_geneset"])

    bams = ' '.join(infiles)    
    tmp_dir = PARAMS["tmp_dir"]
  
    threads = len(infiles)

    if Unpaired==False:
        pair_opts = "-p"
    else:
        pair_opts = " "
    
    # get strandedness for featureCounts
    if PARAMS["strandedness"] == ("RF" or "R"):
        strand = "2"
    elif PARAMS["strandedness"] == ("FR" or "F"):
        strand = "1"
    else:
        strand = "0"

    statement = f'''tmp=`mktemp -p {tmp_dir}` &&
                    gtf=`mktemp -p {tmp_dir}` &&
                    zcat {gtf} > $gtf &&
                    featureCounts
                      -T {threads}
                      -s {strand}
                      -Q 255
                      -t exon
                      -g gene_id
                      {pair_opts}
                      -a $gtf
                      -o $tmp
                      {bams} &&
                    sed 's/bam.dir\///g' $tmp | 
                    sed 's/.bam//g' - > {outfile} &&
                    rm $tmp $gtf'''
    
    P.run(statement, job_threads=threads)

    
@transform(featureCount, suffix(r".txt"), r".load")
def loadFeatureCount(infile, outfile):
    P.load(infile, outfile)
    

#@follows(loadCountTables, loadFeatureCount)
@follows(loadFeatureCount)
def readcounts():
    pass

#####################################################
################# Picard Stats  #####################
#####################################################
@follows(mapping)
@transform("bam.dir/*.bam",
           regex(r"(.*).bam"),
           r"\1.picardAlignmentStats.txt")
def picardAlignmentSummary(infile, outfile):
    '''get alignment summary stats with picard for filtered bams'''

    tmp_dir = PARAMS["tmp_dir"]
    refSeq = os.path.join(PARAMS["genome_dir"], PARAMS["genome"] + ".fa")

    mem = "12G"
    
    statement = f'''tmp=`mktemp -p {tmp_dir}` &&
                    picard -Xmx{mem}
                    CollectAlignmentSummaryMetrics
                      R={refSeq}
                      I={infile}
                      O=$tmp &&
                    cat $tmp | grep -v "#" > {outfile}'''

    P.run(statement, job_threads=3, job_memory=mem)

    
@merge(picardAlignmentSummary,
       "picardAlignmentSummary.load")
def loadpicardAlignmentSummary(infiles, outfile):
    '''load the complexity metrics to a single table in the db'''

    P.concatenate_and_load(infiles, outfile,
                         regex_filename="(.*).picardAlignmentStats",
                         cat="sample_id",
                         options='-i "sample_id"')

    
@active_if(Stranded==True)
@subdivide("bam.dir/*.bam",
           regex(r"(.*).bam"),
           [r"\1.picardRNAseqMetrics.txt",
             r"\1.picardRNAseqMetrics.hist.txt"])
def picardRNAseqMetrics(infile, outfiles):
    '''Run picard RNAseq metrics for stranded libraries.
       Split output into tables for database upload'''

    table, hist = outfiles
    
    tmp_dir = PARAMS["tmp_dir"]
    refSeq = os.path.join(PARAMS["genome_dir"], PARAMS["genome"] + ".fa")

    mem = "12G"

    refFlat = PARAMS["ref_flat"]

    # convert strandedness to PICARD library type
    if PARAMS["strandedness"] == ("RF" or "R"):
        strand = "SECOND_READ_TRANSCRIPTION_STRAND"
    elif PARAMS["strandedness"] == ("FR" or "F"):
        strand = "FIRST_READ_TRANSCRIPTION_STRAND"
    else:
        strand = "NONE"
        
    statement = f'''picard_out=`mktemp -p {tmp_dir}` &&
                    picard -Xmx{mem}
                    CollectRnaSeqMetrics
                      REF_FLAT={refFlat}
                      INPUT={infile}
                      OUTPUT=$picard_out
                      STRAND={strand} &&
                    grep -v "#" $picard_out |
                      grep  "[a-z,A-Z,0-9]" - | head -n2 > {table} &&
                    grep -v "#" $picard_out |
                      sed -n '/normalized_position/,/^[[:blank:]]/p' - > {hist} &&
                    rm $picard_out'''
    
    P.run(statement, job_threads=3, job_memory=mem)

    
@merge("bam.dir/*.picardRNAseqMetrics.txt",
       "picardRNAseqMetrics.load")
def loadPicardRNAseqMetrics(infiles, outfile):
    '''load picardRNAseqMetrics'''

    P.concatenate_and_load(infiles, outfile,
                         regex_filename="(.*).picardRNAseqMetrics",
                         cat="sample_id",
                         options='-i "sample_id"')

       
@follows(loadpicardAlignmentSummary, picardRNAseqMetrics)
def summarystats():
    pass

#####################################################
############### TPMs with Salmon ####################
#####################################################
@follows(mkdir("salmon.dir"))
@active_if(Unpaired==False)
@transform("data.dir/*fastq.1.gz",
           regex(r"data.dir/(.*).fastq.1.gz"),
           r"salmon.dir/\1.log")
def salmon(infile, outfile):
    '''Per sample quantification using salmon'''

    outname = outfile[:-len(".log")]
    salmon_index = PARAMS["salmon_index"] # get salmon quasi-mapping index here
    library_type = PARAMS["salmon_libtype"]
    threads = 8

    read1 = infile
    read2 = read1.replace(".fastq.1.gz", ".fastq.2.gz")

    version = PARAMS["salmon_version"]

    statement = []
    
    if version:
        statement.append(f'''module switch bio/salmon/0.11.3 bio/salmon/{version} && ''')
    
    statement.append(f'''salmon quant 
                           -i {salmon_index}
                           -p {threads}
                           -l {library_type}
                           -1 {read1}
                           -2 {read2}
                           -o {outname}
                         &> {outfile}''')

    statement = ' '.join(statement)

    P.run(statement, job_threads=threads)


@active_if(Unpaired)
@transform("data.dir/*fastq.gz",
           regex(r"data.dir/(.*).fastq.gz"),
           r"salmon.dir/\1.log")
def salmon_SE(infile, outfile):
    '''Per sample quantification using salmon'''

    outname = outfile.replace(".log", "")
    salmon_index = PARAMS["salmon_index"] # get salmon quasi-mapping index here
    library_type = PARAMS["salmon_libtype"]
    threads = 8

    version = PARAMS["salmon_version"]

    statement = []
    
    if version:
        statement.append(f'''module switch bio/salmon/0.11.3 bio/salmon/{version} && ''')
    
    statement.append(f'''salmon quant 
                           -i {salmon_index}
                           -p {threads}
                           -l {library_type}
                           -r {infile}
                           -o {outname}
                         &> {outfile}''')

    statement = ' '.join(statement)

    P.run(statement, job_threads=threads)

    
@follows(salmon, salmon_SE)
@merge("salmon.dir/*log", "salmon.dir/salmon.load")
def loadSalmon(infiles, outfile):
    '''load the salmon results'''

    tables = [x.replace(".log", "/quant.sf") for x in infiles]

    P.concatenate_and_load(tables, outfile,
                         regex_filename=".*/(.*)/quant.sf",
                         cat="sample_id",
                         options="-i Name",
                         job_memory=PARAMS["sql_himem"])

    
@files(loadSalmon,
       "salmon.dir/salmon_genes.txt")
def salmonGeneTable(infile, outfile):
    '''Prepare a per-gene tpm table'''

    table = P.to_table(infile)

    anndb = PARAMS["annotations_database"]
    anndb_table = PARAMS["annotations_dbtable"]
    
    attach = f'''attach "{anndb}" as anndb'''
    con = sqlite3.connect(db)
    c = con.cursor()
    c.execute(attach)

    sql = f'''select sample_id, gene_id, sum(TPM) tpm
             from {table} t
             inner join anndb.{anndb_table} i
             on t.Name=i.transcript_id
             group by gene_id, sample_id'''

    df = pd.read_sql(sql, con)
    df = df.pivot("gene_id", "sample_id", "tpm")
    df.to_csv(outfile, sep="\t", index=True, index_label="gene_id")

    
@transform(salmonGeneTable,
           suffix(".txt"),
           ".load")
def loadSalmonGeneTable(infile, outfile):

    P.load(infile, outfile, options='-i "gene_id"')

    
@follows(loadSalmonGeneTable)
def readquant():
    pass

#####################################################
############### DeepTools Coverage ##################
#####################################################
@follows(readquant)
@transform("star.dir/*.bam",
           regex(r"star.dir/(.*).bam"),
           r"star.dir/\1.coverage.bw")
def bamCoverageRNA(infile, outfile):
    '''Make normalised bigwig tracks with deeptools'''

    norm_method = PARAMS["deeptools_norm_method"]
    
    # STAR MAPQ of 255 indicates uniquely mapped read
    
    if len(infile) > 0:
        if BamTools.is_paired(infile):
            statement = f'''bamCoverage -b {infile} -o {outfile}
                              --binSize 5
                              --normalizeUsing {norm_method}
                              --samFlagInclude 64
                              --centerReads
                              --minMappingQuality 255
                              --smoothLength 10
                              --skipNAs
                              -p "max" '''
                
        else:
            statement = f'''bamCoverage -b {infile} -o {outfile}
                              --binSize 5
                              --normalizeUsing {norm_method}
                              --minMappingQuality 255
                              --smoothLength 10
                              --samFlagExclude 4
                              --centerReads
                              -p "max" '''

        P.run(statement, job_memory="2G", job_threads=10)

@follows(bamCoverageRNA)
def coverage():
    pass

# ---------------------------------------------------
# Generic pipeline tasks
@follows(mapping, summarystats, readcounts, readquant, coverage)
def full():
    pass


@follows(full)
@files(None, "*.nbconvert.html")
def report(infile, outfile):
    '''Generate html report on pipeline results from ipynb template(s)'''

    templates = PARAMS["report_path"]

    if len(templates)==0:
        print("Specify Jupyter ipynb template path in pipeline.ini for html report generation")
        pass
    
    for template in templates:
        infile = os.path.basename(template)
        outfile = infile.replace(".ipynb", ".nbconvert.html")
        nbconvert = infile.replace(".ipynb", ".nbconvert.ipynb")
        tmp = os.path.basename(template)
        
        statement = f'''cp {template} .  &&
                        jupyter nbconvert 
                          --to notebook 
                          --allow-errors 
                          --ExecutePreprocessor.timeout=-1
                          --execute {infile} && 
                        jupyter nbconvert 
                          --to html 
                          --ExecutePreprocessor.timeout=-1
                          --execute {nbconvert} &&
                        rm {tmp}'''

        P.run(statement)

if __name__ == "__main__":
    sys.exit(P.main(sys.argv))
