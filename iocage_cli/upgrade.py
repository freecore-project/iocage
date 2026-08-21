# Copyright (c) 2014-2019, iocage
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted providing that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR ``AS IS'' AND ANY EXPRESS OR
# IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
# OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,
# STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING
# IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
"""upgrade module for the cli."""
import click
import iocage_lib.iocage as ioc

__rootcmd__ = True


@click.command(
    name="upgrade",
    help="Run freebsd-update to upgrade a specified"
    " jail to the RELEASE given.")
@click.argument("jail", required=True)
@click.option("--release", "-r", required=False, help="RELEASE to upgrade to")
@click.option(
    "--basejail", "-b", "to_basejail", is_flag=True, default=False,
    help="Convert a clone or thick jail to a basejail of the RELEASE, then"
    " upgrade it the way basejails are upgraded, without freebsd-update."
    " The jail must be stopped. A snapshot is taken first and the jail is"
    " rolled back to it if the upgrade fails. Not accepted with ALL.")
def cli(jail, release, to_basejail):
    """Runs upgrade with the command given inside the specified jail."""
    skip_jails = bool(jail != 'ALL')
    ioc.IOCage(jail=jail, skip_jails=skip_jails).upgrade(
        release, to_basejail=to_basejail)
