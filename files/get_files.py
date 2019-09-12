#!/usr/bin/env python

import argparse
from Bio import SearchIO
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord
from Bio.Alphabet import IUPAC
import coreapi
import json
import os
import pickle
# Download of Pfam/UniProt via RESTFUL API
from prody.database import pfam, uniprot
import re
import subprocess
import sys

# Defaults
out_dir = os.path.dirname(os.path.realpath(__file__))

# Append JASPAR-profile-inference to path
sys.path.append(os.path.join(out_dir, os.pardir))

# Import globals
from __init__ import Jglobals

#-------------#
# Functions   #
#-------------#

def parse_args():
    """
    This function parses arguments provided via the command line and returns an {argparse} object.
    """

    parser = argparse.ArgumentParser()

    parser.add_argument("-d", "--devel", action="store_true", help="development mode (uses hfaistos; default = False)")
    parser.add_argument("-o", default=out_dir, help="output directory (default = ./)", metavar="DIR")

    return(parser.parse_args())

def main():

    # Parse arguments
    args = parse_args()

    # Get files
    get_files(args.devel, os.path.abspath(args.o))

def get_files(devel=False, out_dir=out_dir):

    # Globals
    global client
    global codec
    global cwd
    global pfam_file_ext
    global profiles_file_ext
    global uniprot_file_ext
    client = coreapi.Client()
    codec = coreapi.codecs.CoreJSONCodec()
    cwd = os.getcwd()
    pfam_file_ext = ".pfam.json"
    profiles_file_ext = ".profiles.json"
    uniprot_file_ext = ".uniprot.json"

    # Create output dir
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    # Get JASPAR URL
    global jaspar_url
    jaspar_url = "http://jaspar.genereg.net/"
    if devel:
        jaspar_url = "http://hfaistos.uio.no:8002/"

    # Download Pfam DBDs
    _download_Pfam_DBDs(out_dir)

    # For each taxon...
    for taxon in Jglobals.taxons:

        # Download JASPAR profiles
        _download_JASPAR_profiles(taxon, out_dir)

        # Download UniProt sequences
        _download_UniProt_sequences(taxon, out_dir)

        # Get Pfam alignments
        _get_Pfam_alignments(taxon, out_dir)

def _download_Pfam_DBDs(out_dir=out_dir):

    # Initialize
    pfam_DBDs = {}
    pfam_ids = set()
    url = "http://cisbp.ccbr.utoronto.ca/data/2.00/DataFiles/Bulk_downloads/EntireDataset/"
    cisbp_file = "TF_Information_all_motifs.txt.zip"
    faulty_pfam_ids = {
        "DUF260": "LOB",
        "FLO_LFY": "SAM_LFY",
    }

    # Skip if Pfam DBD file already exists
    pfam_DBD_file = os.path.join(out_dir, "pfam-DBDs.json")
    if not os.path.exists(pfam_DBD_file):

        # Change dir
        os.chdir(out_dir)

        # Skip if Cis-BP file already exists
        if not os.path.exists(cisbp_file):

            # Download TF info
            os.system("curl --silent -O %s%s" % (url, cisbp_file))

        # Get DBDs
        cmd = "unzip -p %s | cut -f 11 | sort | uniq | grep -v DBDs" % cisbp_file
        process = subprocess.run([cmd], shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # For each output line...
        for line in process.stdout.decode("utf-8").split("\n"):

            # For each Pfam ID...
            for pfam_id in line.split(","):

                    # Skip if not Pfam ID
                    if len(pfam_id) == 0 or pfam_id == "UNKNOWN":
                        continue

                    # Fix faulty Pfam IDs
                    if pfam_id in faulty_pfam_ids:
                        pfam_id = faulty_pfam_ids[pfam_id]

                    # Add Pfam ID
                    pfam_ids.add(pfam_id)

        # Create Pfam dir
        pfam_dir = "pfam-DBDs"
        if not os.path.exists(pfam_dir):
            os.makedirs(pfam_dir)

        # Change dir
        os.chdir(pfam_dir)

        # For each Pfam ID...
        for pfam_id in sorted(pfam_ids):

            # Fetch MSA from Pfam
            msa_file = pfam.fetchPfamMSA(pfam_id, alignment="seed")

            # For each line...
            for line in Jglobals.parse_file(msa_file):

                m = re.search("^#=GF\sID\s+(\S+)$", line)
                if m:
                    pfam_id_std = m.group(1)

                m = re.search("^#=GF\sAC\s+(PF\d{5}).\d+$", line)
                if m:
                    pfam_ac = m.group(1)
                    break

            # HMM build
            hmm_file = "%s.hmm" % pfam_id_std
            cmd = "hmmbuild %s %s" % (hmm_file, msa_file)
            process = subprocess.run([cmd],shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # HMM press
            cmd = "hmmpress -f %s" % hmm_file
            process = subprocess.run([cmd], shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # Add Pfam
            pfam_DBDs.setdefault(pfam_ac, pfam_id_std)

            # Remove MSA file
            os.remove(msa_file)

        # Skip if HMM database of all DBDs already exists
        hmm_db = "all_DBDs.hmm"
        if not os.path.exists(hmm_db):

            # For each HMM file...
            for hmm_file in os.listdir("."):

                # Skip if not HMM file
                if not hmm_file.endswith(".hmm"): continue

                # Add HMM to database
                for line in Jglobals.parse_file(hmm_file):
                    Jglobals.write(hmm_db, line)

            # HMM press
            cmd = "hmmpress -f %s" % hmm_db
            process = subprocess.run([cmd], shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Write
        Jglobals.write(
            pfam_DBD_file,
            json.dumps(pfam_DBDs, sort_keys=True, indent=4, separators=(",", ": "))
        )

        # Change dir
        os.chdir(out_dir)

        # Remove Cis-BP file
        if os.path.exists(cisbp_file):
            os.remove(cisbp_file)

    # Change dir
    os.chdir(cwd)

def _download_JASPAR_profiles(taxon, out_dir=out_dir):

    # Initialize
    url = os.path.join(jaspar_url, "api", "v1", "taxon", taxon)

    # Skip if taxon profiles JSON file already exists
    profiles_json_file = os.path.join(out_dir, taxon + profiles_file_ext)
    if not os.path.exists(profiles_json_file):

        # Initialize
        profiles = {}
        response = client.get(url)
        json_obj = json.loads(codec.encode(response))

        # While there are more pages...
        while json_obj["next"] is not None:

            # For each profile...
            for profile in json_obj["results"]:

                # Add profiles from the CORE collection...
                if profile["collection"] == "CORE":
                    profiles.setdefault(profile["matrix_id"], profile["name"])

            # Go to next page
            response = client.get(json_obj["next"])
            json_obj = json.loads(codec.encode(response))

        # Do last page
        for profile in json_obj["results"]:

            # Add profiles from the CORE collection...
                if profile["collection"] == "CORE":
                    profiles.setdefault(profile["matrix_id"], profile["name"])

        # Write
        Jglobals.write(
            profiles_json_file,
            json.dumps(profiles, sort_keys=True, indent=4, separators=(",", ": "))
        )

def _download_UniProt_sequences(taxon, out_dir=out_dir):

    # Initialize
    faulty_profiles = {
        "MA0024.1": ["Q01094"],
        "MA0046.1": ["P20823"],
        "MA0052.1": ["Q02078"],
        "MA0058.1": ["P61244"],
        "MA0098.1": ["P14921"],
        "MA0110.1": ["P46667"],
        "MA0138.1": ["Q13127"],
        "MA0328.1": ["P0CY08"],
        "MA0529.1": ["Q94513"],
        "MA0529.2": ["Q94513"]
    }
    faulty_sequences = {
        "B9GPL8": [
            "MEEVGAQVAAPIFIHEALSSRYCDMTSMAKKHDLSYQSPNSQLQQHQFLQASREKNWNSK",
            "AWDWDSVDDDGLGLNLGGSLTSVEEPVSRPNKRVRSGSPGNGSYPMCQVDNCKEDLSKAK",
            "DYHRRHKVCQVHSKATKALVGKQMQRFCQQCSRFHPLTEFDEGKRSCRRRLAGHNRRRRK",
            "TQPEDVTSRLLLPGNPDMNNNGNLDIVNLLTALARSQGKTYLPMIDFYVPPFVLTNCPTV",
            "PDKDQLIQILNKINSLPLPMDLAAKLSNIASLNVKNPNQPYLGHQNRLNGTASSPSTNDL",
            "LAVLSTTLAASAPDALAILSQRSSQSSDNDKSKLPGPNQVTVPHLQKRSNVEFPAVGVER",
            "ISRCYESPAEDSDYQIQESRPNLPLQLFSSSPENESRQKPASSGKYFSSDSSNPIEERSP",
            "SSSPPVVQKLFPLQSTAETMKSEKMSVSREVNANVEGDRSHGCVLPLELFRGPNREPDHS",
            "SFQSFPYRGGYTSSSGSDHSPSSQNSDPQDRTGRIIFKLFDKDPSHFPGTLRTKIYNWLS",
            "NSPSEMESYIRPGCVVLSVYLSMPSASWEQLERNLLQLVDSLVQDSDSDLWRSGRFLLNT",
            "GRQLASHKDGKVRLCKSWRTWSSPELILVSPVAVIGGQETSLQLKGRNLTGPGTKIHCTY",
            "MGGYTSKEVTDSSSPGSMYDEINVGGFKIHGPSPSILGRCFIEVENGFKGNSFPVIIADA",
            "SICKELRLLESEFDENAVVSNIVSEEQTRDLGRPRSREEVMHFLNELGWLFQRKSMPSMH",
            "EAPDYSLNRFKFLLIFSVERDYCVLVKTILDMLVERNTCRDELSKEHLEMLYEIQLLNRS",
            "VKRRCRKMADLLIHYSIIGGDNSSRTYIFPPNVGGPGGITPLHLAACASGSDGLVDALTN",
            "DPHEIGLSCWNSVLDANGLSPYAYAVMTKNHSYNLLVARKLADKRNGQISVAIGNEIEQA",
            "ALEQEHVTISQFQRERKSCAKCASVAAKMHGRFLGSQGLLQRPYVHSMLAIAAVCVCVCL",
            "FFRGAPDIGLVAPFKWENLNYGTI"
        ]
    }

    # Change dir
    os.chdir(out_dir)

    # Skip if pickle file already exists
    pickle_file = ".%s.uniaccs.pickle" % taxon
    if not os.path.exists(pickle_file):

        # Initialize
        uniaccs = {}

        # Load JSON file
        profiles_json_file = taxon + profiles_file_ext
        with open(profiles_json_file) as f:
            profiles = json.load(f)

        # For each profile...
        for profile in sorted(profiles):

            # Get profile detailed info
            url = os.path.join(jaspar_url, "api", "v1", "matrix", profile)
            response = client.get(url)
            json_obj = json.loads(codec.encode(response))

            # Fix faulty profiles
            if json_obj["matrix_id"] in faulty_profiles:
                json_obj["uniprot_ids"] = faulty_profiles[json_obj["matrix_id"]]

            # For each UniProt Accession...
            for uniacc in json_obj["uniprot_ids"]:

                # Initialize
                uniacc = uniacc.strip(" ")
                uniaccs.setdefault(uniacc, [[], None])

                # Add uniacc
                if profile not in uniaccs[uniacc][0]:
                    uniaccs[uniacc][0].append(profile)

        # Write pickle file
        with open(pickle_file, "wb") as f:
            pickle.dump(uniaccs, f)

    # Skip if taxon uniprot JSON file already exists
    uniprot_json_file = taxon + uniprot_file_ext
    if not os.path.exists(uniprot_json_file):

        # Load pickle file
        with open(pickle_file, "rb") as f:
            uniaccs = pickle.load(f)

        # For each UniProt Accession...
        for uniacc in uniaccs:

            print(uniacc)

            # Fix faulty sequences
            if uniacc in faulty_sequences:
                uniaccs[uniacc][1] = "".join(faulty_sequences[uniacc]) 
                continue

            # Get UniProt sequence
            u = uniprot.queryUniprot(uniacc)
            uniaccs[uniacc][1] = "".join(u["sequence   0"].split("\n"))

        # Write
        Jglobals.write(
            uniprot_json_file,
            json.dumps(uniaccs, sort_keys=True, indent=4, separators=(",", ": "))
        )

    # Change dir
    os.chdir(cwd)

def _get_Pfam_alignments(taxon, out_dir=out_dir):

    # Skip if Pfam JSON file already exists
    pfam_json_file = os.path.join(out_dir, taxon + pfam_file_ext)
    if not os.path.exists(pfam_json_file):

        # Change dir
        os.chdir(out_dir)

        # Initialize
        pfams = {}
        seq_file = ".seq.fasta"
        hmm_db = os.path.join("pfam-DBDs", "all_DBDs.hmm")
        uniprot_json_file = taxon + uniprot_file_ext

        # Load JSON file
        with open(uniprot_json_file) as f:
            uniaccs = json.load(f)

        # For each uniacc...
        for uniacc in uniaccs:

            # Initialize
            pfams.setdefault(uniacc, [])

            # Make seq file
            seq = Seq(uniaccs[uniacc][1], IUPAC.protein)
            seq_record = SeqRecord(seq, id=uniacc, name=uniacc, description=uniacc)
            _makeSeqFile(seq_record, seq_file)

            # For each DBD...
            for pfam_ac, start, end, evalue in hmmScan(seq_file, hmm_db, non_overlapping_domains=True):

                # Initialize
                hmm_file = os.path.join("pfam-DBDs", "%s.hmm" % pfam_ac)

                # Make seq file
                sub_seq = seq[start:end]
                seq_record = SeqRecord(sub_seq, id=uniacc, name=uniacc, description=uniacc)
                _makeSeqFile(seq_record, seq_file)

                # Add DBDs
                alignment = hmmAlign(seq_file, hmm_file)
                pfams[uniacc].append((pfam_ac, alignment, start+1, end, evalue))

        # Write
        Jglobals.write(
            pfam_json_file,
            json.dumps(pfams, sort_keys=True, indent=4, separators=(",", ": "))
        )

        # Remove seq file
        if os.path.exists(seq_file):
            os.remove(seq_file)

        # Change dir
        os.chdir(cwd)

def _makeSeqFile(seq_record, file_name=".seq.fa"):

    # Remove seq file if exists...
    if os.path.exists(file_name):
        os.remove(file_name)

    # Write
    Jglobals.write(file_name, seq_record.format("fasta"))

def hmmScan(seq_file, hmm_file, non_overlapping_domains=False):

    # Initialize
    out_file = ".out.txt"

    # Scan
    cmd = "hmmscan --domtblout %s %s %s" % (out_file, hmm_file, seq_file)
    process = subprocess.run([cmd], shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Read domains
    domains = _readDomainsTab(out_file)

    # Remove output file
    if os.path.exists(out_file):
        os.remove(out_file)

    # Filter overlapping domains
    if non_overlapping_domains:
        domains = _getNonOverlappingDomains(domains)

    # Yield domains one by one
    for pfam_ac, start, end, evalue in sorted(domains, key=lambda x: x[1]):

        yield(pfam_ac, start, end, evalue)

def _readDomainsTab(file_name):

    # Initialize
    domains = []
    # From PMID:22942020;
    # A hit has equal probability of being in the same clan as a different clan when the
    # E-value is 0.01 (log10 = −2). When the E-value is 10−5, the probability that a sequence
    # belongs to the same clan is >95%.
    cutoff_mod = 1e-5
    # From CIS-BP paper;
    # We scanned all protein sequences for putative DNA-binding domains (DBDs) using the 81
    # Pfam (Finn et al., 2010) models listed in (Weirauch and Hughes, 2011) and the HMMER tool
    # (Eddy, 2009), with the recommended detection thresholds of Per-sequence Eval < 0.01 and
    # Per-domain conditional Eval < 0.01.
    cutoff_dom = 0.01

    # For each result...
    for res in SearchIO.parse(file_name, "hmmscan3-domtab"):

        # For each model...
        for mod in res.iterhits():

            # Skip poor models
            if mod.evalue > cutoff_mod:
                continue

            # For each domain...
            for dom in mod.hsps:

                # Skip poor domains
                if dom.evalue_cond > cutoff_dom:
                    continue

                # Append domain
                domains.append((mod.id, dom.query_start, dom.query_end, dom.evalue_cond))

    return(domains)

def _getNonOverlappingDomains(domains):

    # Initialize
    nov_domains = []

    # Sort domains by e-value
    for domain in sorted(domains, key=lambda x: x[-1]):

        # Initialize
        domains_overlap = False

        # For each non-overlapping domain...
        for nov_domain in nov_domains:

            # domains 1 & 2 overlap?
            # ---------1111111---------
            # -------22222-------------  True
            # ----------22222----------  True
            # -------------22222-------  True
            # -----22222---------------  False
            # ---------------22222-----  False
            if domain[1] < nov_domain[2] and domain[2] > nov_domain[1]:
                domains_overlap = True
                break

        # Add non-overlapping domain
        if not domains_overlap:
            nov_domains.append(domain)

    return(nov_domains)

def hmmAlign(seq_file, hmm_file):

    # Align
    cmd = "hmmalign --outformat PSIBLAST %s %s" % (hmm_file, seq_file)
    process = subprocess.check_output([cmd], shell=True, universal_newlines=True)

    return(_readPSIBLASToutformat(process))

def _readPSIBLASToutformat(psiblast_alignment):

    # Initialize
    alignment = ""

    # For each chunk...
    for chunk in psiblast_alignment.split("\n"):

        # If alignment substring...
        m = re.search("\s+(\S+)$", chunk)
        if m:
            alignment += m.group(1)

    return(alignment)

#-------------#
# Main        #
#-------------#

if __name__ == "__main__":

    main()