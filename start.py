#!/usr/bin/env python3

import os
import sys
import subprocess
import configparser

from logging import getLogger, DEBUG, StreamHandler, Formatter
from logging.handlers import SysLogHandler
logger = getLogger(__name__)
logger.setLevel(DEBUG)
stream = StreamHandler()
syslog = SysLogHandler(address = "/dev/log")
syslog.setFormatter(Formatter("nanate-wan: %(message)s"))
logger.addHandler(stream)
logger.addHandler(syslog)
logger.propagate = False


ipcmd = "/bin/ip"
iwcmd = "/sbin/iw"
iptables = "/sbin/iptables"
docker = "/usr/bin/docker"

def run_cmds(cmds):

    for cmd in cmds :
        logger.info(" ".join(list(map(str, cmd))))
        subprocess.check_output(list(map(str, cmd)))


def setup_gre(config) :
    
    wan_interface = config.get("routing", "wan_interface")
    dmvpn_interface = config.get("routing", "dmvpn_interface")
    dmvpn_addr = config.get("general", "dmvpn_addr")
    gre_key = config.get("routing", "gre_key")
    gre_ttl = config.get("routing", "gre_ttl")

    logger.info("Setup GRE Interface")
    logger.info("  wan_interface   : %s" % wan_interface)
    logger.info("  dmvpn_interface : %s" % dmvpn_interface)
    logger.info("  dmvpn_addr      : %s" % dmvpn_addr)

    cmds = [
        [ "modprobe", "af_key" ],
        [ ipcmd, "tunnel", "add", dmvpn_interface , "mode", "gre",
          "key", gre_key, "ttl", gre_ttl, "dev", wan_interface ],
        [ ipcmd, "addr", "flush", dmvpn_interface],
        [ ipcmd, "addr", "add", "%s/32" % dmvpn_addr, "dev", dmvpn_interface ],
        [ ipcmd, "link", "set", dmvpn_interface, "up" ],
    ]


    if os.path.exists("/sys/class/net/%s" % dmvpn_interface) :
        logger.error("'%s' exists. delete and recreate." % dmvpn_interface)
        cmds.insert(0, [ ipcmd, "tunnel", "del", dmvpn_interface])
    

    run_cmds(cmds)
    
def setup_bridge(config) :

    br_interface = config.get("portconfig", "br_interface")
    
    logger.info("Setup Bridge Interface")
    logger.info("  br_interface : %s" % br_interface)

    cmds = [
        [ ipcmd, "link", "add", br_interface, "type", "bridge",
          "vlan_filtering", 1 ],
        [ ipcmd, "link", "set", "dev", br_interface, "up" ]
    ]

    if os.path.exists("/sys/class/net/%s" %  br_interface) :
        logger.error("'%s' exists. delete and recreate." % br_interface)
        cmds.insert(0, [ ipcmd, "link", "del", "dev", br_interface ])

    run_cmds(cmds)


def setup_nflog(config) :

    logger.info("Setup NFLOG")

    dmvpn_interface = config.get("routing", "dmvpn_interface")

    cmds = [
        [
            "iptables", "-A", "FORWARD",
            "-i", dmvpn_interface, "-o", dmvpn_interface,
            "-m", "hashlimit",
            "--hashlimit-upto", "4/minute",
            "--hashlimit-burst", 1,
            "--hashlimit-mode", "srcip,dstip",
            "--hashlimit-srcmask", 16,
            "--hashlimit-name", "loglimit-0",
            "-j", "NFLOG", "--nflog-group", 1, "--nflog-size", 128
        ]
    ]

    nflog = "iptables -nL --line-numbers | grep NFLOG"
    for line in subprocess.getoutput([nflog]).split("\n") :
        if not line : continue
        logger.error("NFLOG rule '%s' exists. sorry, delete it." % line)
        rulenum = line.split()[0]
        cmds.insert(0, [ iptables, "-D", "FORWARD", rulenum])

    run_cmds(cmds)


def run_containers(config, configpath) :

    logger.info("Start Nante-WAN Docker Containers")

    # check nante-wan containers already running
    cmds = [
        [ docker, "run", "-dt", "--rm", "--privileged", "--net=host",
          "-v", "%s:/etc/nante-wan.conf" % configpath,
          "-v", "/dev/log:/dev/log",
          "upaa/nante-wan-routing"
        ],
        [ docker, "run", "-dt", "--rm", "--privileged", "--net=host",
          "-v", "%s:/etc/nante-wan.conf" % configpath,
          "-v", "/dev/log:/dev/log",
          "upaa/nante-wan-portconfig"
        ],
    ]
    
    dockerps = "docker ps | grep upaa/nante-wan"
    for line in subprocess.getoutput([dockerps]).split("\n") :
        if not line : continue
        c_id = line.split()[0]
        c_name = line.split()[1]
        logger.error("%s is working as %s. delete and re-run" % (c_name, c_id))
        cmds.insert(0, [ docker, "rm", "-f", c_id ])

    run_cmds(cmds)


if __name__ == "__main__"  :

    if len(sys.argv) != 2 :
        print("Usage: %s [Nante-WAN Config]" % sys.argv[0])
        sys.exit(1)

    config = configparser.ConfigParser()
    config.read(sys.argv[1])

    setup_gre(config)
    setup_bridge(config)
    setup_nflog(config)
    run_containers(config, os.path.abspath(sys.argv[1]))