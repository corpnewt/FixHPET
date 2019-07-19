#!/usr/bin/env python
# 0.0.0
from Scripts import *
import os, tempfile, shutil, plistlib, sys, binascii, zipfile

class FixHPET:
    def __init__(self, **kwargs):
        self.dl = downloader.Downloader()
        self.u  = utils.Utils("FixHPET")
        self.r  = run.Run()
        self.re = reveal.Reveal()
        self.iasl_url = "https://bitbucket.org/RehabMan/acpica/downloads/iasl.zip"
        self.iasl = None
        self.dsdt = None
        self.scripts = "Scripts"
        self.output = "Results"
        self._crs = "5F435253"
        self.xcrs = "58435253"
        self.legacy_irq = ["TMR","TIMR","IPIC","RTC"] # Could add HPET for extra patch-ness, but shouldn't be needed
        self.scope = ""
        self.target_irqs = [0,8,11]
        self.ssdt_source = """//
// Supplementary HPET _CRS from Goldfish64
// Requires the HPET's _CRS to XCRS rename
//
DefinitionBlock ("", "SSDT", 2, "hack", "HPET", 0x00000000)
{
    External (_SB_.PCI0.[[scope]], DeviceObj)    // (from opcode)

    Name (\_SB.PCI0.[[scope]].HPET._CRS, ResourceTemplate ()  // _CRS: Current Resource Settings
    {
        IRQNoFlags ()
            {0,8,11}
        Memory32Fixed (ReadWrite,
            0xFED00000,         // Address Base
            0x00000400,         // Address Length
            )
    })
}
"""

    def check_output(self):
        t_folder = os.path.join(os.path.dirname(os.path.realpath(__file__)), self.output)
        if not os.path.isdir(t_folder):
            os.mkdir(t_folder)
        return t_folder
    
    def check_iasl(self):
        self.u.head("Checking For iasl")
        print("")
        target = os.path.join(os.path.dirname(os.path.realpath(__file__)), self.scripts, "iasl")
        if not os.path.exists(target):
            # Need to download
            temp = tempfile.mkdtemp()
            try:
                self._download_and_extract(temp,self.iasl_url)
            except Exception as e:
                print("An error occurred :(\n - {}".format(e))
            shutil.rmtree(temp, ignore_errors=True)
        if os.path.exists(target):
            return target
        return None

    def _download_and_extract(self, temp, url):
        ztemp = tempfile.mkdtemp(dir=temp)
        zfile = os.path.basename(url)
        print("Downloading {}".format(os.path.basename(url)))
        self.dl.stream_to_file(url, os.path.join(ztemp,zfile), False)
        print(" - Extracting")
        btemp = tempfile.mkdtemp(dir=temp)
        # Extract with built-in tools \o/
        with zipfile.ZipFile(os.path.join(ztemp,zfile)) as z:
            z.extractall(os.path.join(temp,btemp))
        script_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), self.scripts)
        for x in os.listdir(os.path.join(temp,btemp)):
            if "iasl" in x.lower():
                # Found one
                print(" - Found {}".format(x))
                print("   - Chmod +x")
                self.r.run({"args":["chmod","+x",os.path.join(btemp,x)]})
                print("   - Copying to {} directory".format(os.path.basename(script_dir)))
                shutil.copy(os.path.join(btemp,x), os.path.join(script_dir,x))

    def list_irqs(self, dsdt):
        # Walks the DSDT keeping track of the current device and
        # saving the IRQNoFlags if found
        devices = {}
        current_device = None
        irq = False
        last_irq = False
        for line in dsdt:
            if ":" in line.split("//")[0]:
                # Skip all hex lines
                continue
            if irq:
                # Get the values
                num = line.split("{")[1].split("}")[0].replace(" ","")
                num = "#" if not len(num) else num
                if current_device in devices:
                    if last_irq: # In a row
                        devices[current_device] += ":"+num
                    else: # Skipped at least one line
                        devices[current_device] += "-"+num
                else:
                    devices[current_device] = line.split("{")[1].split("}")[0]
                irq = False
                last_irq = True
            elif "Device (" in line:
                current_device = line.split("(")[1].split(")")[0]
                last_irq = False
            elif "IRQNoFlags" in line and current_device:
                # Next line has our interrupts
                irq = True
            # Check if just a filler line
            elif len(line.replace("{","").replace("}","").replace("(","").replace(")","").replace(" ","").split("//")[0]):
                # Reset last IRQ as it's not in a row
                last_irq = False
        return devices

    def get_hex_from_int(self, total):
        hex_str = hex(total)[2:].upper().rjust(4,"0")
        return "".join([hex_str[i:i + 2] for i in range(0, len(hex_str), 2)][::-1])

    def get_hex_from_irqs(self, irq, rem_irq = None):
        # We need to search for a few different types:
        #
        # 22 XX XX 22 XX XX 22 XX XX (multiples on different lines)
        # 22 XX XX (summed multiples in the same bracket - {0,8,11})
        # 22 XX XX (single IRQNoFlags entry)
        # 
        # Can end with 79 [00] (end of method), 86 09 (middle of method) or 47 01 (unknown)
        lines = []
        for i in irq.split("-"):
            find = self.get_int_for_line(i)
            repl = [0]*len(find)
            # Now we need to verify if we're patching *all* IRQs, or just some specifics
            if rem_irq:
                repl = [x for x in find]
                matched = []
                for x in rem_irq:
                    # Get the int
                    rem = self.convert_irq_to_int(x)
                    repl = [x&(rem^0xFFFF) if x >= rem else x for x in repl]
            # Get the hex
            d = {
                "irq":i,
                "find": "".join(["22"+self.get_hex_from_int(x) for x in find]),
                "repl": "".join(["22"+self.get_hex_from_int(x) for x in repl])
                }
            d["changed"] = not (d["find"]==d["repl"])
            lines.append(d)
        return lines
        
    def get_int_for_line(self, irq):
        irq_list = []
        for i in irq.split(":"):
            irq_list.append(self.same_line_irq(i))
        return irq_list

    def same_line_irq(self, irq):
        # We sum the IRQ values and return the int
        total = 0
        for i in irq.split(","):
            if i == "#":
                continue # Null value
            try: i=int(i)
            except: continue # Not an int
            if i > 15 or i < 0:
                continue # Out of range
            total = total | self.convert_irq_to_int(i)
        return total

    def convert_irq_to_int(self, irq):
        b = "0"*(15-irq)+"1"+"0"*(irq)
        return int(b,2)

    def get_all_irqs(self, irq):
        irq_list = []
        for i in irq.split("-"):
            for x in i.split(":"):
                for y in x.split(","):
                    if y == "#":
                        continue
                    irq_list.append(int(y))
        return irq_list

    def get_hex(self, line):
        # strip the header and commented end
        return line.split(":")[1].split("//")[0].replace(" ","")

    def get_hex_bytes(self, line):
        return binascii.unhexlify(line)
    
    def find_next_hex(self, dsdt, index):
        # Returns the index of the next set of hex digits after the passed index
        for i,line in enumerate(dsdt[index:]):
            if i == 0:
                # Skip the current index
                continue
            if ":" in line.split("//")[0]: # Checks for a :, but not in comments
                return index+i
        return -1 # Not found

    def find_hpet_crs(self, dsdt):
        found_hpet = False
        found_crs  = False
        for i,line in enumerate(dsdt):
            if ":" in line.split("//")[0]:
                # Skip all hex lines
                continue
            if "Device (HPET)" in line:
                found_hpet = True
                pad = line.split("Device (HPET)")[0]
                continue
            if not found_hpet:
                continue
            # We have the HPET device and such
            if not len(line.strip()):
                # Empty line
                continue
            if "Method (_CRS" in line:
                # Found the _CRS - let's go until we hit the hex
                return self.find_next_hex(dsdt,i)
        return -1

    def get_data(self, data):
        if sys.version_info >= (3, 0):
            return data
        else:
            return plistlib.Data(data)

    def get_clover_patch(self, patch):
        return {
            "Comment": patch["Comment"],
            "Disabled": False,
            "Find": self.get_data(self.get_hex_bytes(patch["Find"])),
            "Replace": self.get_data(self.get_hex_bytes(patch["Replace"]))
        }

    def get_oc_patch(self, patch):
        zero = self.get_data(self.get_hex_bytes("00000000"))
        return {
            "Comment": patch["Comment"],
            "Count": 0,
            "Enabled": True,
            "Find": self.get_data(self.get_hex_bytes(patch["Find"])),
            "Limit": 0,
            "Mask": self.get_data(b""),
            "OemTableId": zero,
            "Replace": self.get_data(self.get_hex_bytes(patch["Replace"])),
            "ReplaceMask": self.get_data(b""),
            "Skip": 0,
            "TableLength": 0,
            "TableSignature": zero
        }

    def main(self):
        cwd = os.getcwd()
        self.iasl = self.check_iasl()
        if not self.iasl:
            # didn't find it - couldn't download it - bail
            exit(1)
        self.u.head()
        print("")
        got_origin = False
        origin_path = ""
        while True:
            dsdt = self.u.grab("Please drag and drop your origin folder or DSDT.aml here:  ")
            dsdt = self.u.check_path(dsdt)
            if not dsdt:
                print(" - I couldn't find that file/folder!")
                continue
            if os.path.isdir(dsdt):
                # Check for DSDT.aml inside
                if os.path.exists(os.path.join(dsdt,"DSDT.aml")):
                    origin_path = dsdt
                    got_origin = True
                    dsdt = os.path.join(dsdt,"DSDT.aml")
                else:
                    print(" - I couldn't locate a DSDT.aml in that folder!")
                    continue
            elif os.path.basename(dsdt).lower() != "dsdt.aml":
                print(" - The dropped file must be DSDT.aml!")
                continue
            print("")
            break
        temp = tempfile.mkdtemp()
        try:
            # Should have a DSDT - try and decompile it with the `-l` flag
            print("Copying to temp folder...")
            if got_origin:
                got_origin = False # Reset until we get an SSDT file copied
                for x in os.listdir(origin_path):
                    if x.startswith(".") or x.lower().startswith("ssdt-x") or not x.lower().endswith(".aml"):
                        # Not needed - skip
                        continue
                    if x.lower().startswith("ssdt"):
                        got_origin = True # Got at least one - nice
                    print(" - {}...".format(x))
                    shutil.copy(os.path.join(origin_path,x),temp)
                dsdt_path = os.path.join(temp,"DSDT.aml")
            else:
                print(" - {}...".format(os.path.basename(dsdt)))
                shutil.copy(dsdt,temp)
                dsdt_path = os.path.join(temp,os.path.basename(dsdt))
            dsdt_l_path = os.path.splitext(dsdt_path)[0]+".dsl"
            
            print("")
            print("Creating a mixed listing file...")
            os.chdir(temp)
            if got_origin:
                # Have at least one SSDT to use while decompiling
                out = self.r.run({"args":"{} -da -dl -l DSDT.aml SSDT*".format(self.iasl),"shell":True})
            else:
                # Just the DSDT - might be incomplete though
                out = self.r.run({"args":[self.iasl,"-da","-dl","-l",dsdt_path]})
            
            if out[2] != 0 or not os.path.exists(dsdt_l_path):
                raise Exception("Failed to decompile {}".format(os.path.basename(dsdt_path)))
            
            print("")
            print("Loading {} and locating HPET...".format(os.path.basename(dsdt_l_path)))
            with open(dsdt_l_path,"r") as f:
                dsdt_c = f.read()
                dsdt_contents = dsdt_c.split("\n")
            hpet_crs = self.find_hpet_crs(dsdt_contents)
            if hpet_crs == -1:
                raise Exception("Could not locate HPET _CRS!")
            print(" - Found HPET _CRS at index {}".format(hpet_crs))
            
            # Save the initial find/replace
            current_crs  = self.get_hex(dsdt_contents[hpet_crs])
            current_xcrs = current_crs.replace(self._crs,self.xcrs)

            print("")
            print("Loading {} and verifying hex data is unique...".format(os.path.basename(dsdt_path)))
            with open(dsdt_path,"rb") as f:
                dsdt_raw = f.read()
            last_index = hpet_crs
            pad = ""
            patches = []
            while True:
                # Check if our hex string is unique
                check_bytes = self.get_hex_bytes(current_crs+pad)
                if dsdt_raw.count(check_bytes) > 2:
                    # More than one instance - add more pad
                    last_index = self.find_next_hex(dsdt_contents,last_index)
                    if last_index == -1:
                        raise Exception("Hit end of file before unique hex was found!")
                    # Got more hex to pad with
                    pad += self.get_hex(dsdt_contents[last_index])
                    continue
                break
            
            print("")
            print(" - _CRS to XCRS Rename:")
            print("      Find: {}".format(current_crs+pad))
            print("   Replace: {}".format(current_xcrs+pad))
            print("")
            patches.append({"Comment":"Rename _CRS to XCRS in HPET","Find":current_crs+pad,"Replace":current_xcrs+pad})

            print("Checking IRQs ({})...".format(",".join([str(x) for x in self.target_irqs]) if len(self.target_irqs) else "All"))
            print("")
            # Now we verify our IRQ checks
            devs = self.list_irqs(dsdt_contents)
            for dev in devs:
                irq_list = self.get_all_irqs(devs[dev])
                has_conflict = [x for x in irq_list if x in [0,8,11]]
                if not dev in self.legacy_irq:
                    if len(has_conflict):
                        con_str = ",".join([str(y) for y in has_conflict])
                        print("!!! Non-Legacy {} IRQs conflict with HPET patch: {} !!!".format(dev,con_str))
                    continue
                irq_patches = self.get_hex_from_irqs(devs[dev],self.target_irqs)
                i = [x for x in irq_patches if x["changed"]]
                for a,t in enumerate(i):
                    if not t["changed"]:
                        # Nothing patched - skip
                        continue
                    # Try our endings here - 7900, 8609, and 4701
                    ending = None
                    for x in ["7900","8609","4701"]:
                        t_bytes = binascii.unhexlify(t["find"]+x)
                        if t_bytes in dsdt_raw:
                            ending = x
                            break
                    if not ending:
                        print("Missing IRQ Patch ending for {}! Skipping...".format(dev))
                        continue
                    t_patch = t["find"]+ending
                    r_patch = t["repl"]+ending
                    name = "{} IRQ {} Patch".format(dev, t["irq"])
                    if len(i) > 1:
                        name += "Patch {} of {}".format(a+1, len(i))
                    patches.append({"Comment":name,"Find":t_patch,"Replace":r_patch})
                    print(" - {}".format(name))
                    print("      Find: {}".format(t_patch))
                    print("   Replace: {}".format(r_patch))
                    print("")

            if "PCI0.LPCB" in dsdt_c:
                self.scope = "LPCB"
            elif "PCI0.LPC" in dsdt_c:
                self.scope = "LPC"
            
            if not self.scope:
                print("")
                print("Could not locate LPCB or LPC in DSDT!")
                print("")
                while True:
                    self.scope = self.u.grab("Please enter the device that HPET is attached to in your DSDT (eg. LPCB or LPC):  ")
                    if not len(self.scope):
                        continue
                    if " " in self.scope:
                        print(" - the device name cannot have spaces")
                        continue
                    break

            print("")
            os.chdir(os.path.dirname(os.path.realpath(__file__)))
            o_folder = self.check_output()
            print("Writing SSDT-HPET.dsl with scope _SB.PCIO.{}".format(self.scope))
            with open(os.path.join(o_folder,"SSDT-HPET.dsl"),"w") as f:
                f.write(self.ssdt_source.replace("[[scope]]",self.scope))
            print("")
            print("Compiling...")
            out = self.r.run({"args":[self.iasl,os.path.join(o_folder,"SSDT-HPET.dsl")]})
            if out[2] != 0 or not os.path.exists(dsdt_l_path):
                raise Exception("Failed to compile SSDT-HPET.dsl!")
            print("")

            # Save a patches_OC.plist and patches_Clover.plist file with our info
            print("Building patches_OC and patches_Clover plists...")
            oc_plist = {"ACPI":{"Patch":[]}}
            cl_plist = {"ACPI":{"DSDT":{"Patches":[]}}}
            # Add the SSDT to the dicts
            oc_plist["ACPI"]["Add"] = [{"Comment":"HPET _CRS (Needs _CRS to XCRS Rename)","Enabled":True,"Path":"SSDT-HPET.aml"}]
            cl_plist["ACPI"]["SortedOrder"] = ["SSDT-HPET.aml"]
            # Iterate the patches
            for p in patches:
                oc_plist["ACPI"]["Patch"].append(self.get_oc_patch(p))
                cl_plist["ACPI"]["DSDT"]["Patches"].append(self.get_clover_patch(p))

            # Write the plists
            with open(os.path.join(o_folder,"patches_OC.plist"),"wb") as f:
                plist.dump(oc_plist,f)
            with open(os.path.join(o_folder,"patches_Clover.plist"),"wb") as f:
                plist.dump(cl_plist,f)

            print("")
            print("Done.")
            self.re.reveal(os.path.join(o_folder,"patches_Clover.plist"))
        except Exception as e:
            print("An error occurred :(\n - {}".format(e))
            pass
        shutil.rmtree(temp,ignore_errors=True)
        os.chdir(cwd)
            
if __name__ == '__main__':
    f = FixHPET()
    f.main()
