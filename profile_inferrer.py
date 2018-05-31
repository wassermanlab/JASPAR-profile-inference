#!/usr/bin/env python2.7
import os
from Bio import pairwise2
from Bio.Blast import NCBIXML
from Bio.SubsMat.MatrixInfo import blosum62
import json
import optparse
import shutil
import subprocess
from tqdm import tqdm

# Import my functions #
import functions

#-------------#
# Functions   #
#-------------#

def parse_options():
    """
    This function parses the command line arguments and returns an optparse
    object.

    """

    parser = optparse.OptionParser("./%prog -f <files_dir> -i <input_file> [-b <blast_dir> -m <mmseqs_dir>] [--dummy=<dummy_dir> -n <n_parameter> -o <output_file> -t <taxon>] [-l -s]")

    parser.add_option("-f", action="store", type="string", dest="files_dir", help="Files directory (output directory from make_files.py)", metavar="<files_dir>")
    parser.add_option("-i", action="store", type="string", dest="input_file", help="Input file (i.e. one or more sequences in FASTA format)", metavar="<input_file>")
    parser.

    group = optparse.OptionGroup(parser, "Homology searching options")
    parser.add_option("-b", action="store", type="string", dest="blast_dir", help="Full path to BLAST+ bin directory (i.e. where \"makeblastdb\" is located; e.g. $BLAST_PATH/bin)", metavar="<blast_dir>")
    group.add_option("-m", action="store", type="string", dest="mmseqs_dir", help="Full path to MMseqs2 bin directory (i.e. where \"mmseqs\" is located; e.g. $MMSEQS_PATH/bin)", metavar="<mmseqs_dir>")
    
    group = optparse.OptionGroup(parser, "Non-mandatory options")
    group.add_option("--dummy", default="/tmp/", action="store", type="string", dest="dummy_dir", help="Dummy directory (default = /tmp/)", metavar="<dummy_dir>")
    group.add_option("-n", default=0, action="store", type="int", dest="n_parameter", help="N parameter for the Rost's curve (e.g. n=5 ensures 99% of correctly assigned homologs; default = 0)", metavar="<n_parameter>")
    group.add_option("-o", action="store", type="string", dest="output_file", help="Output file (default = stdout)", metavar="<output_file>")
    group.add_option("-t", action="store", dest="taxon", help="Taxonomic group (i.e. \"fungi\", \"insects\", \"nematodes\", \"plants\", or \"vertebrates\"; default = None)", metavar="<taxon>")
    group.add_option("--threads", action="store", dest="taxon", help="To be implemented", metavar="<threads>")
    parser.add_option_group(group)
    
    group = optparse.OptionGroup(parser, "Inference modes")
    group.add_option("-l", "--latest", default=False, action="store_true", dest="latest", help="Latest mode (return the latest version of a profile; default = False)")
    group.add_option("-s", "--single", default=False, action="store_true", dest="single", help="Singleton mode (return profiles from a single TF; default = False)")
    parser.add_option_group(group)

    (options, args) = parser.parse_args()

    if options.files_dir is None or options.input_file is None:
        parser.error("missing arguments: type option \"-h\" for help")

    if options.blast_dir is None and options.mmseqs_dir is None:
        parser.error("missing an homology searching method:\n\tspecify full path to either BLAST+ (option \"-b\") or MMseqs2 (option \"-m\") bin directory")
    
    if options.blast_dir is not None and options.mmseqs_dir is not None:
        parser.error("specify ONLY one homology searching method:\n\ti.e. full path to either BLAST+ (option \"-b\") or MMseqs2 (option \"-m\") bin directory")

    if options.taxon is not None:
        if options.taxon not in ["fungi", "insects", "nematodes", "plants", "vertebrates"]:
            parser.error("invalid taxon: %s\n\tvalid taxons include \"fungi\", \"insects\", \"nematodes\", \"plants\", and \"vertebrates\"" % options.taxon)

    return options

def is_alignment_over_Rost_sequence_identity_curve(identities, align_length, parameter=0):
    """
    This function evaluates whether an alignment is over {True} or 
    below {False} the Rost's sequence identity curve.
    
    @input:
    identities {int}
    align_length {int}
    parameter {int} N parameter in the curve (if > 0 more strict)
    @return: {boolean}
    
    """
    return identities >= get_Rost_ID_threshold(align_length, n=parameter)

def get_Rost_ID_threshold(L, n=0):
    """
    This function returns the Rost sequence identity threshold for a
    given alignment of length "L".

    @input:
    L {int} alignment length
    parameter {int} N parameter in the curve (if > 0 more strict)
    @return: {Decimal}
        
    """
    import math

    return n + (480*pow(L,float('-0.32')*(1+pow(float(repr(math.e)),float(repr(float(-L)/1000))))))

def get_alignment_identities(A, B):
    """
    This function returns the number of identities between a pair
    of aligned sequences {A} and {B}. If {A} and {B} have different
    lengths, returns None.

    @input:
    A {string} aligned sequence A (with residues and gaps)
    B {string} aligned sequence B (with residues and gaps)
    @return: {int} or None

    """
    if len(A) == len(B):
        return len([i for i in range(len(A)) if A[i] == B[i]])

    return None

#-------------#
# Main        #
#-------------#

if __name__ == "__main__":

    # Arguments & Options #
    options = parse_options()

    # Initialize #
    homologs = {}
    query_sequences = {}
    jaspar_sequences = {}
    inferences = []
    dummy_dir = os.path.join(os.path.abspath(options.dummy_dir), "%s.%s" % (os.path.basename(__file__), os.getpid()))
    if not os.path.exists(dummy_dir): os.makedirs(dummy_dir)
    query_mmseqs_db = os.path.join(dummy_dir, "query.db")
    query_mmseqs_ali = os.path.join(dummy_dir, "query.ali")
    query_tsv = os.path.join(dummy_dir, "query.tsv")
    jaspar_mmseqs_db = os.path.join(os.path.abspath(options.files_dir), "sequences.fa.db")
    jaspar_blast_db = os.path.join(os.path.abspath(options.files_dir), "sequences.fa")
    if options.taxon is not None:
        jaspar_mmseqs_db = os.path.join(os.path.abspath(options.files_dir), "%s.fa.db" % options.taxon)
        jaspar_blast_db = os.path.join(os.path.abspath(options.files_dir), "%s.fa" % options.taxon)
    domains_json = os.path.join(os.path.abspath(options.files_dir), "domains.json")
    domains = json.loads("\n".join([line for line in functions.parse_file(domains_json)]))
#    tsv_file = os.path.join(os.path.abspath(options.dummy_dir), "%s.%s.tsv" % (os.path.basename(__file__), os.getpid()))
#    csv_file = os.path.join(os.path.abspath(options.dummy_dir), "%s.%s.csv" % (os.path.basename(__file__), os.getpid()))
#    fasta_file = os.path.join(os.path.abspath(options.dummy_dir), "%s.%s.fa" % (os.path.basename(__file__), str(os.getpid())))
#    blast_file = os.path.join(os.path.abspath(options.dummy_dir), "%s.%s.xml" % (os.path.basename(__file__), str(os.getpid())))
#    
#    jaspar_json = os.path.join(os.path.abspath(options.files_dir), "jaspar.json")
#    jaspar = json.loads("\n".join([line for line in functions.parse_file(jaspar_json)]))
#    database_file = os.path.join(os.path.abspath(options.files_dir), "sequences.fa")
#    if options.taxon is not None:
#        database_file = os.path.join(os.path.abspath(options.files_dir), "%s.fa" % options.taxon)


#    process = subprocess.check_output([os.path.join(os.path.abspath(options.mmseqs_dir), "mmseqs"), "createindex", "%s.db" % fasta_file, os.path.abspath(options.dummy_dir)], stderr=subprocess.STDOUT)
    # Write output #
    #functions.write(csv_file, "#Query,TF Name,TF Matrix,E-value,Query Alignment,Query Start-End,TF Alignment,TF Start-End,DBD %ID")

    # For each header, sequence... #
    for header, sequence in functions.parse_fasta_file(os.path.abspath(options.input_file)):
        query_sequences.setdefault(header, sequence)  

    # For each header, sequence... #
    for header, sequence in functions.parse_fasta_file(jaspar_blast_db):
        jaspar_sequences.setdefault(header, sequence)

    # Create db #
    try:
        process = subprocess.check_output([os.path.join(os.path.abspath(options.mmseqs_dir), "mmseqs"), "createdb", os.path.abspath(options.input_file), query_db], stderr=subprocess.STDOUT)
    except:
        raise ValueError("Could not create MMseqs2 db: %s" % query_db)

    # Index db #
    try:
#        process = subprocess.check_output([os.path.join(os.path.abspath(options.mmseqs_dir), "mmseqs"), "createindex", query_db, os.path.abspath(options.dummy_dir), "--threads", "1"], stderr=subprocess.STDOUT)
        process = subprocess.check_output([os.path.join(os.path.abspath(options.mmseqs_dir), "mmseqs"), "createindex", query_db, os.path.abspath(options.dummy_dir)], stderr=subprocess.STDOUT)
    except:
        raise ValueError("Could not index MMseqs2 db: %s" % query_db)

    # Search JASPAR db #
    try:
#        process = subprocess.check_output([os.path.join(os.path.abspath(options.mmseqs_dir), "mmseqs"), "search", jaspar_db, query_db, query_ali, dummy_dir, "-s", "7.5", "--threads", "1"], stderr=subprocess.STDOUT)
        process = subprocess.check_output([os.path.join(os.path.abspath(options.mmseqs_dir), "mmseqs"), "search", jaspar_db, query_db, query_ali, dummy_dir, "-s", "7.5"], stderr=subprocess.STDOUT)
    except:
        raise ValueError("Could not search JASPAR db!")

    # Reformat alignments #
    try:
#        process = subprocess.check_output([os.path.join(os.path.abspath(options.mmseqs_dir), "mmseqs"), "convertalis", jaspar_db, query_db, query_ali, query_tsv, "--threads", "1"], stderr=subprocess.STDOUT)
        process = subprocess.check_output([os.path.join(os.path.abspath(options.mmseqs_dir), "mmseqs"), "convertalis", jaspar_db, query_db, query_ali, query_tsv], stderr=subprocess.STDOUT)
    except:
        raise ValueError("Could not reformat alignments!")

    # For each line... #
    for line in functions.parse_file(query_tsv):
        # The file is formatted as a tab-separated list with 12 columns: (1,2) identifiers for query and target sequences/profiles, (3) sequence identity, (4) alignment length, (5) number of mismatches, (6) number of gap openings, (7-8, 9-10) domain start and end-position in query and in target, (11) E-value, and (12) bit score.
        target, query, perc_identity, alignment_length, mismatches, gaps, target_start, target_end, query_start, query_end, e_value, score = line.split("\t")
        if is_alignment_over_Rost_sequence_identity_curve(int(alignment_length) - int(mismatches), int(alignment_length), parameter=int(options.n_parameter)):
            homologs.setdefault(query, [])
            homologs[query].append([float(e_value), target, int(query_start), int(query_end), int(target_start), int(target_end)])

    # For each header, sequence... #
    for header, sequence in functions.parse_fasta_file():
        header = header.split()
        # For each homolog... #
        for homolog in homologs:
            # If homolog... #
            if homolog in header[0]:
                sequences.setdefault(homolog, sequence)
                break
                
    
    # For each query... #
    for query in tqdm(sorted(homologs), desc="TF inference"):
        # For each E-value, target, and domain start and end-position in query and in target... #
        for e_value, target, query_start, query_end, target_start, target_end in homologs[query]:
            # Skip if target does not have assigned domains... #
            if target not in domains: continue
            # Initialize #
            identities = [0]
            sequence = sequences[query][query_start - 1:query_end]
            # For each domain... #
            for domain in domains[uniacc][0]:
                # Pairwise alignment #
                try:
                    alignments = pairwise2.align.globalds(sequence, domain, blosum62, -11.0, -1)
                except:
                    raise ValueError("Pairwise alignment failed:\n\tA: %s\n\tB: %s" % (sequence, domain))
                for alignment in alignments:
                        identities.append(get_alignment_identities(alignment[0], alignment[1])/float(len(domain)))
            # If domain alignment passes threshold... #
            if max(identities) >= float(domains[uniacc][1]):
                # For each uniacc JASPAR matrix... #
                for matrix, genename in jaspar[uniacc]:
                    # Infer matrix #
                    inferences.append([query, genename, matrix, e_value, "%s-%s" % (query_start, query_end), "%s-%s" % (target_start, target_end), max(identities)])
        # For each inferred profile... #
        for inference in sorted(inferences, key=lambda x: (x[-1], x[1]), reverse=True):
            # If latest mode... #
            if options.latest:
                if inference[1][:6] in inferred_profiles: continue
            # If single mode... #
            if options.single:
                if "::" in inference[0]: continue
            # Write output #
            functions.write(csv_file, "%s,%s" % (header, ",".join(map(str, inference))))
            inferred_profiles.add(inference[1][:6])

    # Output #
    if options.output_file is not None:
        # Write output #
        shutil.copy(csv_file, os.path.abspath(options.output_file))
    else:
        # For each line... #
        for line in functions.parse_file(dummy_file):
            # Write output #
            functions.write(None, line)
    # Remove files #
    if os.path.exists(csv_file): os.remove(csv_file)


#    # For each header, sequence... #
#    for header, sequence in tqdm(sequences, desc="TF inference"):
#        # Initialize #
#        homologs = []
#        inferences = []
#        inferred_profiles = set()
#        # Remove files #
#        if os.path.exists(blast_file): os.remove(blast_file)
#        if os.path.exists(fasta_file): os.remove(fasta_file)
#        # Create FASTA file #
#        functions.write(fasta_file, ">%s\n%s" % (header, sequence))
#        # Exec blastp #
#        try:
#            process = subprocess.check_output([os.path.join(os.path.abspath(options.blast_dir), "blastp"), "-query", fasta_file, "-db", database_file, "-out", blast_file, "-outfmt", "5"], stderr=subprocess.STDOUT)
#        except:
#            raise ValueError("Could not exec blastp for %s" % fasta_file)
#        # Parse BLAST results #
#        blast_records = NCBIXML.parse(open(blast_file))
#        # For each blast record... #
#        for blast_record in blast_records:
#            for alignment in blast_record.alignments:
#                for hsp in alignment.hsps:
#                    # If structural homologs... #
#                    if is_alignment_over_Rost_sequence_identity_curve(hsp.identities, hsp.align_length, parameter=int(options.n_parameter)):
#                        homologs.append((str(alignment.hit_def), float(hsp.expect), hsp.query, "%s-%s" % (hsp.query_start, hsp.query_end),  hsp.sbjct, "%s-%s" % (hsp.sbjct_start, hsp.sbjct_end)))
#                        break
#        # Remove files #
#        if os.path.exists(blast_file): os.remove(blast_file)
#        if os.path.exists(fasta_file): os.remove(fasta_file)
#        # For each uniacc... #
#        for uniacc, evalue, query_alignment, query_from_to, hit_alignment, hit_from_to in homologs:
#            # Skip if uniacc does not have assigned domains... #
#            if uniacc not in domains: continue
#            # Initialize #
#            identities = [0]
#            # For each domain... #
#            for domain in domains[uniacc][0]:
#                # Pairwise alignment #
#                try:
#                    alignments = pairwise2.align.globalds(sequence, domain, blosum62, -11.0, -1)
#                except:
#                    raise ValueError("Pairwise alignment failed:\n\tA: %s\n\tB: %s" % (sequence, domain))
#                for alignment in alignments:
#                        identities.append(get_alignment_identities(alignment[0], alignment[1])/float(len(domain)))
#            # If domain alignment passes threshold... #
#            if max(identities) >= float(domains[uniacc][1]):
#                # For each uniacc JASPAR matrix... #
#                for matrix, genename in jaspar[uniacc]:
#                    # Infer matrix #
#                    inferences.append([genename, matrix, evalue, query_alignment, query_from_to, hit_alignment, hit_from_to, max(identities)])
#        # For each inferred profile... #
#        for inference in sorted(inferences, key=lambda x: (x[-1], x[1]), reverse=True):
#            # If latest mode... #
#            if options.latest:
#                if inference[1][:6] in inferred_profiles: continue
#            # If single mode... #
#            if options.single:
#                if "::" in inference[0]: continue
#            # Write output #
#            functions.write(csv_file, "%s,%s" % (header, ",".join(map(str, inference))))
#            inferred_profiles.add(inference[1][:6])
#
#    # Output #
#    if options.output_file is not None:
#        # Write output #
#        shutil.copy(csv_file, os.path.abspath(options.output_file))
#    else:
#        # For each line... #
#        for line in functions.parse_file(dummy_file):
#            # Write output #
#            functions.write(None, line)
#    # Remove files #
#    if os.path.exists(csv_file): os.remove(csv_file)