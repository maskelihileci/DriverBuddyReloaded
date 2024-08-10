"""
A script to help you find desired opcodes/instructions in a database

The script accepts opcodes and assembly statements (which will be assembled) separated by semicolon

The general syntax is:
  find(asm or opcodes, x=Bool, asm_where=ea)

* Example:
  find("asm_statement1;asm_statement2;de ea dc 0d e0;asm_statement3;xx yy zz;...")
* To filter-out non-executable segments pass x=True
  find("jmp dword ptr [esp]", x=True)
* To specify in which context the instructions should be assembled, pass asm_where=ea:
  find("jmp dword ptr [esp]", asm_where=here())

Copyright (c) 1990-2021 Hex-Rays
ALL RIGHTS RESERVED.
"""
import re
import sys

import ida_bytes
import ida_funcs
import ida_ida
import ida_idaapi
import ida_kernwin
import ida_lines
import ida_search
import ida_segment
import ida_ua
import idautils
from DriverBuddyReloaded.vulnerable_functions_lists.opcode import *

# This option will prevent Driver Buddy Reloaded to find opcodes in data sections
# https://github.com/VoidSec/DriverBuddyReloaded/issues/11
# switch it to true to see something along this line:
# - Found jnz     short loc_15862 in sub_15820 at 0x00015852
# going at that address and defining the selection as code will usually bring the searched opcode back
# prone to false positives
find_opcode_data = False

def find_binary_alternative(start_ea, end_ea, bin_str, search_flags):
    # Convert binary string to bytes
    bin_bytes = bytes.fromhex(bin_str.replace(' ', ''))
    
    # Initialize the search start address
    ea = start_ea
    
    # Iterate through the range and search for the byte pattern
    while ea != ida_idaapi.BADADDR and ea < end_ea:
        ea = ida_bytes.find_bytes(
            range_start=ea, 
            range_end=end_ea, 
            bs=bin_bytes, 
            flags=search_flags
        )
        if ea != ida_idaapi.BADADDR:
            return ea
        ea += 1  # Move to the next address
    
    return ida_idaapi.BADADDR


def FindInstructions(instr, asm_where=None):
    """
    Finds instructions/opcodes
    :param instr:
    :param asm_where:
    :return: Returns a tuple(True, [ ea, ... ]) or a tuple(False, "error message")
    """

    if not asm_where:
        # get first segment
        seg = ida_segment.get_first_seg()
        asm_where = seg.start_ea if seg else ida_idaapi.BADADDR
        if asm_where == ida_idaapi.BADADDR:
            return False, "No segments defined"

    # regular expression to distinguish between opcodes and instructions
    re_opcode = re.compile('^[0-9a-f]{2} *', re.I)

    # split lines
    lines = instr.split(";")

    # all the assembled buffers (for each instruction)
    bufs = []
    for line in lines:
        if re_opcode.match(line):
            # convert from hex string to a character list then join the list to form one string
            buf = bytes(bytearray([int(x, 16) for x in line.split()]))
        else:
            # assemble the instruction
            ret, buf = idautils.Assemble(asm_where, line)
            if not ret:
                return False, "Failed to assemble: {}".format(line)
        # add the assembled buffer
        bufs.append(buf)

    # join the buffer into one string
    buf = b''.join(bufs)

    # take total assembled instructions length
    tlen = len(buf)

    # convert from binary string to space separated hex string
    bin_str = ' '.join(["%02X" % (ord(x) if sys.version_info.major < 3 else x) for x in buf])

    # find all binary strings
    # print("[>] Searching for opcode {} - [{}]...".format(instr, bin_str))
    ea = ida_ida.inf_get_min_ea()  # Call the function to get the starting address
    ret = []
    while True:
        search_flags = ida_bytes.BIN_SEARCH_FORWARD | ida_bytes.BIN_SEARCH_NOSHOW  # Search direction flag
        ea = find_binary_alternative(ea, ida_idaapi.BADADDR, bin_str, search_flags)
        if ea == ida_idaapi.BADADDR:
            break
        ret.append(ea)
        # ida_kernwin.msg(".")
        ea += tlen
    if not ret:
        return False, "Could not match {} - [{}]".format(instr, bin_str)
    # ida_kernwin.msg("\n")
    return True, ret


# Chooser class
class SearchResultChoose(ida_kernwin.Choose):
    def __init__(self, title, items):
        ida_kernwin.Choose.__init__(
            self,
            title,
            [["Address", 30], ["Function (or segment)", 25], ["Instruction", 20]],
            width=250)
        self.items = items

    def OnGetSize(self):
        return len(self.items)

    def OnGetLine(self, n):
        i = self.items[n]
        ea = i.ea
        return [
            hex(i.ea),
            i.funcname_or_segname,
            i.text
        ]

    def OnSelectLine(self, n):
        ida_kernwin.jumpto(self.items[n].ea)


# class to represent the results
class SearchResult:
    def __init__(self, ea, log_file):
        self.ea = ea
        self.funcname_or_segname = ""
        self.text = ""
        if not ida_bytes.is_code(ida_bytes.get_flags(ea)):
            ida_ua.create_insn(ea)

        # text
        t = ida_lines.generate_disasm_line(ea)
        if t:
            self.text = ida_lines.tag_remove(t)

        # funcname_or_segname
        n = ida_funcs.get_func_name(ea) \
            or ida_segment.get_segm_name(ida_segment.getseg(ea))
        if n:
            self.funcname_or_segname = n
        if find_opcode_data is False:
            for opcode in opcodes:
                if opcode in self.text:
                    print(
                        "\t- Found {} in {} at 0x{addr:08x}".format(self.text, self.funcname_or_segname, addr=self.ea))
                    log_file.write("\t- Found {} in {} at 0x{addr:08x}\n".format(self.text, self.funcname_or_segname,
                                                                                 addr=self.ea))
        else:
            print("\t- Found {} in {} at 0x{addr:08x}".format(self.text, self.funcname_or_segname, addr=self.ea))
            log_file.write(
                "\t- Found {} in {} at 0x{addr:08x}\n".format(self.text, self.funcname_or_segname, addr=self.ea))


def find(log_file, s=None, x=False, asm_where=None):
    """
    Search for opcode/instruction
    :param log_file: log file handler
    :param s: opcode/instruction
    :param x: if true search for executable code segments only
    :param asm_where: where to start searching
    :return:
    """

    b, ret = FindInstructions(s, asm_where)
    if b:
        # executable segs only?
        if x:
            results = []
            for ea in ret:
                seg = ida_segment.getseg(ea)
                if (not seg) or (seg.perm & ida_segment.SEGPERM_EXEC) == 0:
                    continue
                results.append(SearchResult(ea, log_file))
        else:
            results = [SearchResult(ea, log_file) for ea in ret]
        """title = "Search result for: [%s]" % s
        ida_kernwin.close_chooser(title)
        c = SearchResultChoose(title, results)
        c.Show(True)"""
    # else:
    # print(ret)
