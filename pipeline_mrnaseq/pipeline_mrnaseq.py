##############################################################################
#
#   MRC FGU CGAT
#
#   $Id$
#
#   Copyright (C) 2017 Tariq Khoyratty
#
#   This program is free software; you can redistribute it and/or
#   modify it under the terms of the GNU General Public License
#   as published by the Free Software Foundation; either version 2
#   of the License, or (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program; if not, write to the Free Software
#   Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
###############################################################################
"""===========================
Pipeline template
===========================

:Author: Tariq Khoyratty
:Release: $Id$
:Date: |today|
:Tags: Python

Overview
========

This pipeline is for the processing of mapped mRNA-seq reads.
Reads in Ensembl protein coding genes are counted with featureCounts,
& quantified with Cufflinks. Raw counts are also reported for 
differential expression analysis.

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

The pipeline requires the results from
:doc:`pipeline_annotations`. Set the configuration variable
:py:data:`annotations_database` and :py:data:`annotations_dir`.

On top of the default CGAT setup, the pipeline requires the following
software to be in the path:

.. Add any additional external requirements such as 3rd party software
   or R modules below:

Requirements:

* samtools >= 1.1

Pipeline output
===============

Raw counts of reads in genes, and normalised counts from Cufflinks

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
import CGAT.Experiment as E
import CGATPipelines.Pipeline as P
import CGAT.BamTools as BamTools
import pandas as pd
import re


# load options from the config file
PARAMS = P.getParameters(
    ["%s/pipeline.ini" % os.path.splitext(__file__)[0],
     "../pipeline.ini",
     "pipeline.ini"])

# add configuration values from associated pipelines
#
# 1. pipeline_annotations: any parameters will be added with the
#    prefix "annotations_". The interface will be updated with
#    "annotations_dir" to point to the absolute path names.
# PARAMS.update(P.peekParameters(
#     PARAMS["annotations_dir"],
#     "pipeline_annotations.py",
#     on_error_raise=__name__ == "__main__",
#     prefix="annotations_",
#     update_interface=True))


# if necessary, update the PARAMS dictionary in any modules file.
# e.g.:
#
# import CGATPipelines.PipelineGeneset as PipelineGeneset
# PipelineGeneset.PARAMS = PARAMS
#
# Note that this is a hack and deprecated, better pass all
# parameters that are needed by a function explicitely.

# -----------------------------------------------
# Utility functions
def connect():
    '''utility function to connect to database.

    Use this method to connect to the pipeline database.
    Additional databases can be attached here as well.

    Returns an sqlite3 database handle.
    '''

    dbh = sqlite3.connect(PARAMS["database"])
    statement = '''ATTACH DATABASE '%s' as annotations''' % (
        PARAMS["annotations_database"])
    cc = dbh.cursor()
    cc.execute(statement)
    cc.close()

    return dbh

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

#####################################################
#################### Mapping ########################
#####################################################
#@follows(connect, mkdir("star.dir"))
@follows(mkdir("star.dir"))
@active_if(Unpaired==False)
@transform("data.dir/*_1.fastq.gz",
           regex(r"data.dir/(.*)_1.fastq.gz"),
           r"star.dir/\1.bam")
def starMapping(infile, outfile):

    genomeDir = PARAMS["star_index_dir"]

    job_threads = "12"

    tmpdir = "$SCRATCH_DIR"
    log_prefix = outfile.rstrip(".bam") + "."

    read1 = infile
    read2 = read1.replace("_1.fastq.gz", "_2.fastq.gz")
    
    statement = '''tmp=`mktemp -p %(tmpdir)s`; checkpoint;
                   STAR 
                     --runMode alignReads 
                     --runThreadN 12 
                     --genomeDir %(genomeDir)s
                     --outSAMstrandField intronMotif 
                     --outFileNamePrefix %(log_prefix)s
                     --outStd SAM 
                     --outSAMunmapped Within 
                     --outFilterMismatchNmax 2 
                     --readFilesIn %(read1)s %(read2)s
                     --readFilesCommand zcat | samtools view -b - 
                     >  $tmp; checkpoint;
                   samtools sort -O BAM  $tmp > %(outfile)s; checkpoint;
                   rm $tmp''' % locals()

    print(statement)

    P.run()

@active_if(Unpaired)
@transform("data.dir/*.fastq.gz",
           regex(r"data.dir/(.*).fastq.gz"),
           r"star.dir/\1.bam")
def starMapping_SE(infile, outfile):

    genomeDir = PARAMS["star_index_dir"]

    job_threads = "12"

    tmpdir = "$SCRATCH_DIR"
    log_prefix = outfile.rstrip(".bam") + "."
    
    statement = '''tmp=`mktemp -p %(tmpdir)s`; checkpoint;
                   STAR 
                     --runMode alignReads 
                     --runThreadN 12 
                     --genomeDir %(genomeDir)s
                     --outSAMstrandField intronMotif 
                     --outFileNamePrefix %(log_prefix)s
                     --outStd SAM 
                     --outSAMunmapped Within 
                     --outFilterMismatchNmax 2 
                     --readFilesIn %(infile)s 
                     --readFilesCommand zcat | samtools view -b - 
                     >  $tmp; checkpoint;
                   samtools sort -O BAM  $tmp > %(outfile)s; checkpoint;
                   rm $tmp''' % locals()

    print(statement)

    P.run()

@follows(starMapping, starMapping_SE)
@transform("star.dir/*.bam", suffix(r".bam"), r".bam.bai")
def indexBam(infile, outfile):

    statement = '''samtools index -b %(infile)s %(outfile)s'''

    P.run()
    
@follows(starMapping, starMapping_SE)
@transform("star.dir/*.bam", suffix(r".bam"), r"_sort.bam")
def nameSort(infile, outfile):

    statement = '''samtools sort -n -O BAM  %(infile)s > %(outfile)s'''

    P.run()

@follows(indexBam, nameSort)
def mapping():
    pass
    
#####################################################
################## Raw counts #######################
#####################################################
@follows(mapping, mkdir("read_counts.dir"))
@transform("star.dir/*_sort.bam",
           regex(r".*/(.*)_sort.bam"),
           add_inputs(os.path.join(PARAMS["annotations_dir"],
                      PARAMS["annotations_ensembl_geneset"])),
           r"read_counts.dir/\1_counts.txt")
def htseq_count(infiles, outfile):
    '''Count reads falling in ensembl genes'''

    bam, gtf = infiles
    tmp_dir = "$SCRATCH_DIR"

    # htseq-count filters out multi-mapping reads by default (as these can cause false positives
    # for differential expression analysis. The filtering is based on the NH optional SAM field.
    # Not all aligners set this field, so it is safer to filter reads on their MAPQ score as well,
    # to prevent counting multi-mapping reads multiple times.

    ### STAR does have this field, so filtering on MAPQ score isn't required.
    
    # htseq-count -a 255 <- filters out reads with MAPQ < 255 (uniquely mapped in STAR)
    # so no removal of low quality / multimapping reads required prior to counting
    
    statement = '''geneset=`mktemp -p %(tmp_dir)s`; checkpoint ;
                   zcat %(gtf)s > $geneset ; checkpoint ;
                   htseq-count 
                     -a 255 
                     -s no 
                     -m union 
                     -f bam 
                     -r name
                     -t exon
                     -i gene_id 
                     %(bam)s 
                     $geneset
                   > %(outfile)s ; checkpoint ;
                   rm $geneset''' % locals()

    print(statement)
    
    P.run()

@transform(htseq_count, suffix(r".txt"), r".load")
def loadhtseq_count(infile, outfile):
    P.load(infile, outfile, options='-H "gene_id,raw_counts" ')

@follows(loadhtseq_count)   
@transform(htseq_count,
           suffix("_counts.txt"),
           "_table.txt")
def prepareCountTables(infile, outfile):

    statement = '''echo -e "gene_id\\tcounts" > %(outfile)s;
                   grep -v "__" %(infile)s
                   >> %(outfile)s;
                '''
    P.run()

@merge(prepareCountTables, "htseq.counts.load")
def loadCountTables(infiles, outfile):

    P.concatenateAndLoad(infiles, outfile,
                         regex_filename=".*/(.*)_table.txt",
                         cat = "track",
                         options = '-i "gene_id"')

##########################################################################
@follows(mapping)
@merge("star.dir/*_sort.bam", "read_counts.dir/featureCounts.txt")
def featureCount(infiles, outfile):
    '''Count reads falling in ensembl genes (including introns)'''

    gtf = os.path.join(PARAMS["annotations_dir"], PARAMS["annotations_ensembl_geneset"])

    bams = ' '.join(infiles)    
    tmp_dir = "$SCRATCH_DIR"
  
    threads = len(infiles)
    job_threads = threads
    
    statement = '''tmp=`mktemp -p %(tmp_dir)s`; checkpoint ;
                   gtf=`mktemp -p %(tmp_dir)s`; checkpoint ;
                   zcat %(gtf)s > $gtf; checkpoint;
                   featureCounts
                     -T %(threads)s
                     -s 0
                     -S fr
                     -Q 255
                     -t exon
                     -g gene_id
                     -p
                     -a $gtf
                     -o $tmp
                     %(bams)s ; checkpoint ;
                   sed 's/star.dir\///g' $tmp | 
                   sed 's/.bam//g' - > %(outfile)s ; checkpoint;
                   rm $tmp $gtf''' % locals()
                  
    print(statement)
    
    P.run()

@transform(featureCount, suffix(r".txt"), r".load")
def loadFeatureCount(infile, outfile):
    P.load(infile, outfile)

@follows(loadCountTables, loadFeatureCount)
def readcounts():
    pass

#####################################################
################# Picard Stats  #####################
#####################################################
@follows(mapping)
@transform(starMapping,
           regex(r"(.*).bam"),
           r"\1.picardAlignmentStats.txt")
def picardAlignmentSummary(infile, outfile):
    '''get alignment summary stats with picard for filtered bams'''

    tmp_dir = "$SCRATCH_DIR"
    refSeq = os.path.join(PARAMS["genome_dir"], PARAMS["genome"] + ".fa")

    job_threads = "4"
    job_memory = "5G"
    
    statement = '''tmp=`mktemp -p %(tmp_dir)s`; checkpoint ;
                   CollectAlignmentSummaryMetrics
                     R=%(refSeq)s
                     I=%(infile)s
                     O=$tmp; checkpoint ;
                   cat $tmp | grep -v "#" > %(outfile)s'''

    print(statement)

    P.run()

@merge(picardAlignmentSummary,
       "picardAlignmentSummary.load")
def loadpicardAlignmentSummary(infiles, outfile):
    '''load the complexity metrics to a single table in the db'''

    P.concatenateAndLoad(infiles, outfile,
                         regex_filename="(.*).picardAlignmentStats",
                         cat="sample_id",
                         options='-i "sample_id"')

@follows(loadpicardAlignmentSummary)
def summarystats():
    pass

#####################################################
############### TPMs with Salmon ####################
#####################################################
@follows(mkdir("salmon.dir"))
@active_if(Unpaired==False)
@transform("data.dir/*fastq.gz",
           regex(r"data.dir/(.*)_1.fastq.gz"),
           r"salmon.dir/\1.log")
def salmon(infile, outfile):
    '''Per sample quantification using salmon'''

    outname = outfile[:-len(".log")]
    salmon_index = PARAMS["salmon_index"] # get salmon quasi-mapping index here

    job_threads = "8"

    read1 = infile
    read2 = read1.replace("_1.fastq.gz", "_2.fastq.gz")
    
    statement = '''salmon quant 
                     -i %(salmon_index)s
                     -p 8
                     -1 %(read1)s
                     -2 %(read2)s
                     -l IU
                     -o %(outname)s
                   &> %(outfile)s;
              '''
    P.run()

@active_if(Unpaired)
@transform("data.dir/*fastq.gz",
           regex(r"data.dir/(.*).fastq.gz"),
           r"salmon.dir/\1.log")
def salmon_SE(infile, outfile):
    '''Per sample quantification using salmon'''

    outname = outfile[:-len(".log")]
    salmon_index = PARAMS["salmon_index"] # get salmon quasi-mapping index here

    job_threads = "8"

    statement = '''salmon quant 
                     -i %(salmon_index)s
                     -p 8
                     -r %(infile)s
                     -l IU
                     -o %(outname)s
                   &> %(outfile)s;
              '''
    P.run()

@follows(salmon, salmon_SE)
@merge("salmon.dir/*log", "salmon.dir/salmon.load")
def loadSalmon(infiles, outfile):
    '''load the salmon results'''

    tables = [x.replace(".log", "/quant.sf") for x in infiles]

    P.concatenateAndLoad(tables, outfile,
                         regex_filename=".*/(.*)/quant.sf",
                         cat="sample_id",
                         options="-i Name",
                         job_memory=PARAMS["sql_himem"])

@files(loadSalmon,
       "salmon.dir/salmon_genes.txt")
def salmonGeneTable(infile, outfile):
    '''Prepare a per-gene tpm table'''

    table = P.toTable(infile)
    anndb = PARAMS["annotations_database"]

    attach = '''attach "%(anndb)s" as anndb''' % locals()
    con = sqlite3.connect(PARAMS["database_name"])
    c = con.cursor()
    c.execute(attach)

    sql = '''select sample_id, gene_id, sum(TPM) tpm
             from %(table)s t
             inner join anndb.transcript_info i
             on t.Name=i.transcript_id
             group by gene_id, sample_id
          ''' % locals()

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

    job_memory = "2G"
    job_threads = "10"

    # files w/ suffix "_sort.bam" are sorted by name but not indexed, do not use these
    infile = ' '.join([x for x in [infile] if "_sort.bam" not in x])
    ### this is a hack, add suffix to sorted bams so that they can be distinguished from the name sorted files in globs
    
    # STAR MAPQ of 255 indicates uniquely mapped read
    
    if len(infile) > 0:
        if BamTools.isPaired(infile):

            statement = '''bamCoverage -b %(infile)s -o %(outfile)s
                        --binSize 5
                        --normalizeUsingRPKM
                        --samFlagInclude 64
                        --centerReads
                        --minMappingQuality 255
                        --smoothLength 10
                        --skipNAs'''

        else:
            statement = '''bamCoverage -b %(infile)s -o %(outfile)s
                        --binSize 5
                        --normalizeUsingRPKM
                        --minMappingQuality 255
                        --smoothLength 10
                        --samFlagExclude 4
                        --centerReads'''

        # centerReads option and small binsize should increase resolution around enriched areas
        P.run()

@follows(bamCoverageRNA)
def coverage():
    pass

# ---------------------------------------------------
# Generic pipeline tasks
@follows(mapping, summarystats, readcounts, readquant, coverage)
def full():
    pass


@follows(mkdir("report"))
def build_report():
    '''build report from scratch.

    Any existing report will be overwritten.
    '''

    E.info("starting report build process from scratch")
    P.run_report(clean=True)


@follows(mkdir("report"))
def update_report():
    '''update report.

    This will update a report with any changes inside the report
    document or code. Note that updates to the data will not cause
    relevant sections to be updated. Use the cgatreport-clean utility
    first.
    '''

    E.info("updating report")
    P.run_report(clean=False)


@follows(update_report)
def publish_report():
    '''publish report in the CGAT downloads directory.'''

    E.info("publishing report")
    P.publish_report()

if __name__ == "__main__":
    sys.exit(P.main(sys.argv))
