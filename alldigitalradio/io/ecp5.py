from nmigen import *
from nmigen.cli import main

PFD_MIN = 3.125
PFD_MAX = 400
VCO_MIN = 400
VCO_MAX = 800

def find_pll_params(input, output):
    freqs = []

    for input_div in range(1,129):

        fpfd = input / float(input_div)

        if fpfd < PFD_MIN:
            continue
        if fpfd > PFD_MAX:
            continue

        for feedback_div in range(1, 81):
            for output_div in range(1,129):
                fvco = fpfd * float(feedback_div) * float(output_div)

                if fvco < VCO_MIN or fvco > VCO_MAX:
                    continue

                fout = fvco / float(output_div)
                
                if fout == output:
                    return (input_div, feedback_div, output_div)

                freqs.append(fout)

    return sorted(list(set(freqs)))

class PLL(Elaboratable):
    def __init__(self, output=None, clock_freq=48, desired_freq=96):
        self.clock_freq = clock_freq
        self.desired_freq = desired_freq
        self.output = output

    def elaborate(self, platform):
        m = Module()

        #print("Possible Frequencies")
        #pprint(find_pll_params(self.clock_freq, None))

        input_div, feedback_div, output_div = find_pll_params(self.clock_freq, self.desired_freq)
        
        m.submodules.multiplier = Instance(
            "EHXPLLL",
            a_FREQUENCY_PIN_CLKI=str(self.clock_freq),
            a_FREQUENCY_PIN_CLKOP=str(self.desired_freq),
            a_ICP_CURRENT="12",
            a_LPF_RESISTOR="8",
            a_MFG_ENABLE_FILTEROPAMP="1",
            a_MFG_GMCREF_SEL="2",

            p_PLLRST_ENA="DISABLED",
            p_INTFB_WAKE="DISABLED",
            p_STDBY_ENABLE="DISABLED",
            p_OUTDIVIDER_MUXA="DIVA",
            p_OUTDIVIDER_MUXB="DIVB",
            p_OUTDIVIDER_MUXC="DIVC",
            p_OUTDIVIDER_MUXD="DIVD",
            p_CLKI_DIV=input_div,
            p_CLKOP_ENABLE="ENABLED",
            p_CLKOP_DIV=output_div,
            p_CLKOP_CPHASE=0,
            p_CLKOP_FPHASE=0,
            p_FEEDBK_PATH="CLKOP",
            p_CLKFB_DIV=feedback_div,

            i_RST=0,
            i_STDBY=0,
            i_CLKI=ClockSignal(),
            o_CLKOP=self.output,
            i_CLKFB=self.output,
            # i_CLKINTFB
            i_PHASESEL0=0,
            i_PHASESEL1=0,
            i_PHASEDIR=1,
            i_PHASESTEP=1,
            i_PHASELOADREG=1,
            i_PLLWAKESYNC=0,
            i_ENCLKOP=1
            # o_LOCK
        )

        return m


class ECP5Serdes(Elaboratable):
    def __init__(self, enable_tx=False, enable_rx=False, reference_clock=None, external_clock=False, generated_clock=None, tx_domain="tx", rx_domain="rx", idx=0):
        self.enable_tx = enable_tx
        self.enable_rx = enable_rx
        self.reference_clock = reference_clock or Signal()
        self.external_clock = external_clock
        self.tx_domain = tx_domain
        self.rx_domain = rx_domain
        self.generated_clock = generated_clock or (int(5e9) if not external_clock else False)
        self.idx = 0

        if self.generated_clock:
            self.pll = PLL(output=self.reference_clock, clock_freq=12, desired_freq=int(self.generated_clock/25e6))
        else:
            self.pll = None

        self.fifo_clock = Signal()

        self.tx_data = Signal(20)
        self.tx_clock = Signal()

        self.rx_data = Signal(20)
        self.rx_clock = Signal()

        self.rx_data = Signal(20)

        self.rx_locked = Signal()

        self.sci_write_data = Signal(8, reset=0b00000000)
        self.sci_addr = Signal(6, reset=0b0000)

        #self.sci_write_data = Signal(8, reset=0b00000000)
        #self.sci_addr = Signal(6, reset=0x1a)

        self.sci_write = Signal()
        self.sci_read = Signal()
        self.sci_out = Signal(8)
        self.rx_reset = Signal()

    def elaborate(self, platform):
        m = Module()

        if self.external_clock:
            m.submodules.extref0 = Instance("EXTREFB",
                    o_REFCLKO=self.reference_clock, # The reference clock is output to ref_clk, it is not really accessible as a signal, since it only exists within the SERDES
                    p_REFCK_PWDNB="0b1",
                    p_REFCK_RTERM="0b1",            # 100 ohm
                    p_REFCK_DCBIAS_EN="0b0",
                    a_LOC='EXTREF0' if self.idx == 0 else 'EXTREF1'
            )

        m.domains += ClockDomain(self.tx_domain, reset_less=True)
        m.d.comb += ClockSignal(self.tx_domain).eq(self.tx_clock)

        m.domains += ClockDomain(self.rx_domain, reset_less=True)
        m.d.comb += ClockSignal(self.rx_domain).eq(self.rx_clock)

        counter = Signal(24)

        if self.pll:
            m.submodules.pll = self.pll

        # This is a janky state machine to tell the SERDES block to "lock" to the
        # reference, which really means "don't lock to the data" because it looks
        # like the CDR just never really locks in this scenario and slides around
        # 
        # Cleaning this up is a TODO, there are many magic constants here and I
        # don't remember if they're actually correct
        if False:
            with m.FSM() as fsm:
                with m.State("START"):
                    m.d.sync += self.sci_write_data.eq(0b01000000)
                    m.d.sync += self.sci_addr.eq(0b011000)
                    m.next = "WRITE1"

                with m.State("WRITE1"):
                    m.d.sync += self.sci_write.eq(1)
                    m.next = "WRITE"

                with m.State("WRITE"):
                    m.d.sync += self.sci_write.eq(0)
                    m.next = "RESET"

                with m.State("RESET"):
                    m.d.sync += self.rx_reset.eq(1)
                    m.d.sync += counter.eq(1)
                    m.next = "WAIT_SYNC"

                with m.State("WAIT_SYNC"):
                    m.d.sync += counter.eq(counter + 1)
                    m.d.sync += self.rx_reset.eq(0)
                    with m.If(counter == 0):
                        m.next = "DISABLE_RECAL"

                with m.State("DISABLE_RECAL"):
                    m.d.sync += self.sci_write.eq(0)
                    m.d.sync += self.rx_reset.eq(0)
                    m.d.sync += [
                        self.sci_addr.eq(0x1a),
                        self.sci_write_data.eq(0b11111001),
                        #self.sci_addr.eq(0x16),
                        #self.sci_write_data.eq(0b01000001),
                    ]
                    m.next = "DONE"

                with m.State("WAIT"):
                    m.d.sync += self.sci_write.eq(1)
                    m.next = "HMM"

                with m.State("HMM"):
                    m.d.sync += self.sci_write.eq(0)
                    m.d.sync += [
                        self.sci_addr.eq(0x1a),
                        self.sci_write_data.eq(0b11001001),
                    ]
                    m.next = "HMM2"

                with m.State("HMM2"):
                    m.d.sync += self.sci_write.eq(1)
                    m.next = "DONE"

                with m.State("DONE"):
                    m.d.sync += self.rx_reset.eq(0)
                    m.d.sync += self.sci_write.eq(0)
                    #m.d.sync += self.sci_addr.eq(0b011000)
                    m.d.sync += self.sci_addr.eq(0x37),
                    m.d.sync += self.sci_read.eq(1)

        m.submodules.dcu0 = Instance("DCUA",
                a_LOC='DCU0' if self.idx == 0 else 'DCU1',

                # DCU Power Management
                p_D_MACROPDB            = "0b1",
                p_D_IB_PWDNB            = "0b1",    # undocumented (required for TX)
                p_D_TXPLL_PWDNB         = "0b1",
                i_D_FFC_MACROPDB = 1,

                i_D_REFCLKI=self.reference_clock,
                p_D_REFCK_MODE = "0b100",
                p_D_TX_MAX_RATE = "5.0",
                p_D_TX_VCO_CK_DIV = "0b000",
                p_D_BITCLK_LOCAL_EN     = "0b1",
                p_D_SYNC_LOCAL_EN       = "0b1",

                p_D_CMUSETBIASI         = "0b00",   # begin undocumented (PCIe sample code used)
                p_D_CMUSETI4CPP         = "0d4",
                p_D_CMUSETI4CPZ         = "0d3",
                p_D_CMUSETI4VCO         = "0b00",
                p_D_CMUSETICP4P         = "0b01",
                p_D_CMUSETICP4Z         = "0b101",
                p_D_CMUSETINITVCT       = "0b00",
                p_D_CMUSETISCL4VCO      = "0b000",
                p_D_CMUSETP1GM          = "0b000",
                p_D_CMUSETP2AGM         = "0b000",
                p_D_CMUSETZGM           = "0b100",
                p_D_SETIRPOLY_AUX       = "0b10",
                p_D_SETICONST_AUX       = "0b01",
                p_D_SETIRPOLY_CH        = "0b10",
                p_D_SETICONST_CH        = "0b10",
                p_D_SETPLLRC            = "0d1",
                p_D_RG_EN               = "0b0",
                p_D_RG_SET              = "0b00",   # end undocumented

                #o_tx_full_clk_ch0=txpll,

                p_CH0_PROTOCOL = "10BSER",
                p_CH0_UC_MODE = "0b1",
                p_CH0_RTERM_TX="0d19", # 50 ohm termination    

                # CH0 TX — power management
                p_CH0_TPWDNB            = "0b1",
                p_CH0_TX_CM_SEL= "0b00",

                p_CH0_TDRV_SLICE0_CUR   = "0b111",  # 400 uA
                p_CH0_TDRV_SLICE0_SEL   = "0b01",   # main data

                p_CH0_TDRV_SLICE1_CUR   = "0b111",  # 400 uA
                p_CH0_TDRV_SLICE1_SEL   = "0b01",   # main data

                p_CH0_TDRV_SLICE2_CUR   = "0b11",   # 3200 uA
                p_CH0_TDRV_SLICE2_SEL   = "0b01",   # main data

                p_CH0_TDRV_SLICE3_CUR   = "0b11",   # 3200 uA
                p_CH0_TDRV_SLICE3_SEL   = "0b01",   # main data

                p_CH0_TDRV_SLICE4_CUR   = "0b11",   # 3200 uA
                p_CH0_TDRV_SLICE4_SEL   = "0b01",   # main data

                p_CH0_TDRV_SLICE5_CUR   = "0b11",   # 800 uA
                p_CH0_TDRV_SLICE5_SEL   = "0b01",   # power down

                #p_CH0_TDRV_DAT_SEL = "0b01",

                i_CH0_FF_TXI_CLK        = self.tx_clock,

                # TX Gearing

                #p_CH0_TX_GEAR_MODE="0b0", # Don't Gear" 2:1
                #p_CH0_TX_GEAR_BYPASS="0b1", # Don't Gear" 2:1
                #p_CH0_FF_TX_H_CLK_EN="0b0", # Enable half clock
                #o_CH0_FF_TX_F_CLK       = self.tx_clock,

                p_CH0_TX_GEAR_MODE="0b1", # Don't Gear" 2:1
                p_CH0_TX_GEAR_BYPASS="0b0", # Don't Gear" 2:1
                p_CH0_FF_TX_H_CLK_EN="0b1", # Enable half clock
                o_CH0_FF_TX_H_CLK       = self.tx_clock,

                p_CH0_SB_BYPASS="0b1", # Don't invert TX data
                p_CH0_WA_BYPASS="0b1", # Bypass word alignment
                p_CH0_ENC_BYPASS="0b1", # Bypass 8b10b encoder

                i_CH0_FF_TX_D_0=self.tx_data[0],
                i_CH0_FF_TX_D_1=self.tx_data[1],
                i_CH0_FF_TX_D_2=self.tx_data[2],
                i_CH0_FF_TX_D_3=self.tx_data[3],
                i_CH0_FF_TX_D_4=self.tx_data[4],
                i_CH0_FF_TX_D_5=self.tx_data[5],
                i_CH0_FF_TX_D_6=self.tx_data[6],
                i_CH0_FF_TX_D_7=self.tx_data[7],
                i_CH0_FF_TX_D_8=self.tx_data[8],
                i_CH0_FF_TX_D_9=self.tx_data[9],
                i_CH0_FF_TX_D_12=self.tx_data[10],
                i_CH0_FF_TX_D_13=self.tx_data[11],
                i_CH0_FF_TX_D_14=self.tx_data[12],
                i_CH0_FF_TX_D_15=self.tx_data[13],
                i_CH0_FF_TX_D_16=self.tx_data[14],
                i_CH0_FF_TX_D_17=self.tx_data[15],
                i_CH0_FF_TX_D_18=self.tx_data[16],
                i_CH0_FF_TX_D_19=self.tx_data[17],
                i_CH0_FF_TX_D_20=self.tx_data[18],
                i_CH0_FF_TX_D_21=self.tx_data[19],

                # These can be used to passthrough the signal directly to/from FPGA fabric
                #p_CH0_LDR_CORE2TX_SEL=1,
                #i_CH0_FFC_LDR_CORE2TX_EN=~button,
                #i_CH0_LDR_CORE2TX=txpll, #ClockSignal(),
                p_CH0_ENABLE_CG_ALIGN = "0b0", # Comma Alignment


                i_CH0_RX_REFCLK=self.reference_clock,
                o_CH0_FF_RX_H_CLK=self.rx_clock,
                i_CH0_FF_RXI_CLK=self.rx_clock,
                i_CH0_FF_EBRD_CLK=self.rx_clock,
                i_CH0_FFC_RATE_MODE_RX=0,

                p_CH0_RPWDNB = "0b1",
                i_CH0_FFC_RXPWDNB = 1,

                p_D_RX_MAX_RATE = "6.0",
                p_CH0_CDR_MAX_RATE = "6.0",

                p_CH0_RCV_DCC_EN= "0b0", # Enable DC Coupling
                p_CH0_RXTERM_CM = "0b01", # AC Floating
                p_CH0_RXIN_CM = "0b11", # CMFB voltage for equializer

                p_CH0_REQ_EN="0b0", # Enable equalization (seems to improve things)
                p_CH0_REQ_LVL_SET="0b10",
                p_D_REQ_ISET="0b011",
                p_D_PD_ISET="0b11",

                p_CH0_RTERM_RX="0d22",

                p_CH0_AUTO_FACQ_EN="0b1",
                p_CH0_AUTO_CALIB_EN="0b1",
                p_CH0_RX_DCO_CK_DIV="0b000",
                p_CH0_SEL_SD_RX_CLK="0b1", # Select the recovered clock or not
                p_CH0_CALIB_CK_MODE="0b0",

                p_CH0_DCOATDCFG         = "0b00",   # begin undocumented (sample code used)
                p_CH0_DCOATDDLY         = "0b00",
                p_CH0_DCOBYPSATD        = "0b1",
                p_CH0_DCOCALDIV         = "0b010",
                p_CH0_DCOCTLGI          = "0b011",
                p_CH0_DCODISBDAVOID     = "0b1",
                p_CH0_DCOFLTDAC         = "0b00",
                p_CH0_DCOFTNRG          = "0b010",
                p_CH0_DCOIOSTUNE        = "0b010",
                p_CH0_DCOITUNE          = "0b00",
                p_CH0_DCOITUNE4LSB      = "0b010",
                p_CH0_DCOIUPDNX2        = "0b1",
                p_CH0_DCONUOFLSB        = "0b010",
                p_CH0_DCOSCALEI         = "0b00",
                p_CH0_DCOSTARTVAL       = "0b001",
                p_CH0_DCOSTEP           = "0b11",   # end undocumented
                p_CH0_BAND_THRESHOLD    = "0d0",

                #p_CH0_SB_LOOPBACK="0b1",

                #i_CH0_FFC_FB_LOOPBACK = 1,

                p_CH0_DEC_BYPASS="0b1",
                p_CH0_RX_GEAR_BYPASS="0b0", # Do Gear" 2:1
                i_CH0_FFC_RX_GEAR_MODE=1,
                p_CH0_RX_GEAR_MODE="0b1",
                p_CH0_CTC_BYPASS="0b1", # Bypass clock toleration compensation
                p_CH0_LSM_DISABLE="0b1",
                p_CH0_MIN_IPG_CNT = "0b00",

                #p_CH0_SEL_SD_RX_CLK="0b1",
                p_CH0_FF_RX_H_CLK_EN="0b1",
                p_CH0_FF_RX_F_CLK_DIS="0b1",

                p_CH0_PDEN_SEL="0b1", 
                p_CH0_RLOS_SEL="0b1",
                p_CH0_RX_LOS_LVL="0b111",

                p_D_CDR_LOL_SET="0b11",
                o_CH0_FFS_RLOL=self.rx_locked,
                i_CH0_FFC_RRST=self.rx_reset,

                o_CH0_FF_RX_D_0=self.rx_data[0],
                o_CH0_FF_RX_D_1=self.rx_data[1],
                o_CH0_FF_RX_D_2=self.rx_data[2],
                o_CH0_FF_RX_D_3=self.rx_data[3],
                o_CH0_FF_RX_D_4=self.rx_data[4],
                o_CH0_FF_RX_D_5=self.rx_data[5],
                o_CH0_FF_RX_D_6=self.rx_data[6],
                o_CH0_FF_RX_D_7=self.rx_data[7],
                o_CH0_FF_RX_D_8=self.rx_data[8],
                o_CH0_FF_RX_D_9=self.rx_data[9],
                o_CH0_FF_RX_D_12=self.rx_data[10],
                o_CH0_FF_RX_D_13=self.rx_data[11],
                o_CH0_FF_RX_D_14=self.rx_data[12],
                o_CH0_FF_RX_D_15=self.rx_data[13],
                o_CH0_FF_RX_D_16=self.rx_data[14],
                o_CH0_FF_RX_D_17=self.rx_data[15],
                o_CH0_FF_RX_D_18=self.rx_data[16],
                o_CH0_FF_RX_D_19=self.rx_data[17],
                o_CH0_FF_RX_D_20=self.rx_data[18],
                o_CH0_FF_RX_D_21=self.rx_data[19],

                i_D_SCIWDATA0=self.sci_write_data[0],
                i_D_SCIWDATA1=self.sci_write_data[1],
                i_D_SCIWDATA2=self.sci_write_data[2],
                i_D_SCIWDATA3=self.sci_write_data[3],
                i_D_SCIWDATA4=self.sci_write_data[4],
                i_D_SCIWDATA5=self.sci_write_data[5],
                i_D_SCIWDATA6=self.sci_write_data[6],
                i_D_SCIWDATA7=self.sci_write_data[7],

                i_D_SCIADDR0=self.sci_addr[0],
                i_D_SCIADDR1=self.sci_addr[1],
                i_D_SCIADDR2=self.sci_addr[2],
                i_D_SCIADDR3=self.sci_addr[3],
                i_D_SCIADDR4=self.sci_addr[4],
                i_D_SCIADDR5=self.sci_addr[5],

                i_D_SCIWSTN=self.sci_write,

                i_CH0_SCIEN=1,
                i_CH0_SCISEL=1,
                i_D_SCIENAUX=0,
                i_D_SCISELAUX=0,

                i_D_SCIRD=self.sci_read,
                o_D_SCIRDATA0=self.sci_out[0],
                o_D_SCIRDATA1=self.sci_out[1],
                o_D_SCIRDATA2=self.sci_out[2],
                o_D_SCIRDATA3=self.sci_out[3],
                o_D_SCIRDATA4=self.sci_out[4],
                o_D_SCIRDATA5=self.sci_out[5],
                o_D_SCIRDATA6=self.sci_out[6],
                o_D_SCIRDATA7=self.sci_out[7],
        )

        return m
