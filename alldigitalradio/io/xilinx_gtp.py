# Adapted from LiteICLink to nmigen
#
# Copyright (c) 2017-2020 Florent Kermarrec <florent@enjoy-digital.fr>
# Copyright (c) 2017 Sebastien Bourdeauducq <sb@m-labs.hk>
# Copyright (c) 2021 Ben Newhouse <newhouseb@gmail.com>
# SPDX-License-Identifier: BSD-2-Clause

from math import ceil

from nmigen import *
from nmigen.lib.cdc import FFSynchronizer, PulseSynchronizer, ResetSynchronizer
from nmigen.utils import bits_for
from nmigen.build import DiffPairs

from alldigitalradio.io.generic_serdes import GenericSerdes

class XilinxGTPSerdes(GenericSerdes):
    def __init__(self, refclk_freq=125e6, line_rate=5e9):
        super().__init__(refclk_freq=refclk_freq, line_rate=line_rate)

    def elaborate(self, platform):
        m = Module()

        refclk = Signal()
        m.submodules.clock = Instance('IBUFDS_GTE2',
            o_O=refclk,
            i_I=platform.request('clk_p', dir='-'),
            i_IB=platform.request('clk_n', dir='-'),
            i_CEB=0)
        m.submodules.pll = pll = GTPQuadPLL(refclk, 125e6, 5e9)
        m.submodules.gtp = gtp = GTP(pll, 
            [platform.request('tx_n', dir='-'), platform.request('tx_p', dir='-')], 
            [platform.request('rx_n', dir='-'), platform.request('rx_p', dir='-')], 
            25e6, tx_buffer_enable=True, rx_buffer_enable=True)

        return m

class WaitTimer(Elaboratable):
    def __init__(self, t):
        self.t = t
        self.wait = Signal()
        self.done = Signal()

    def elaborate(self, platform):
        m = Module()

        count = Signal(bits_for(self.t), reset=self.t)
        m.d.comb += self.done.eq(count == 0)
        with m.If(self.wait):
            with m.If(~self.done):
                m.d.sync += count.eq(count - 1)
        with m.Else():
            m.d.sync += count.eq(count.reset)

        return m

# GTP Quad PLL -------------------------------------------------------------------------------------

class GTPQuadPLL(Elaboratable):
    def __init__(self, refclk, refclk_freq, linerate, channel=0, shared=False):
        assert channel in [0, 1]
        self.channel = channel
        self.clk     = Signal()
        self.inrefclk  = refclk
        self.refclk = Signal()
        self.reset   = Signal()
        self.lock    = Signal()
        self.config  = self.compute_config(refclk_freq, linerate)
        self.shared = shared

    def elaborate(self, platform):
        m = Module()

        if not self.shared:
            gtpe2_common_params = dict(
                # common
                i_GTREFCLK0    = self.inrefclk,
                i_BGBYPASSB    = 1,
                i_BGMONITORENB = 1,
                i_BGPDB        = 1,
                i_BGRCALOVRD   = 0b11111,
                i_RCALENB      = 1,
            )

            if self.channel == 0:
                gtpe2_common_params.update(
                    # pll0
                    p_PLL0_FBDIV      = self.config["n2"],
                    p_PLL0_FBDIV_45   = self.config["n1"],
                    p_PLL0_REFCLK_DIV = self.config["m"],
                    i_PLL0LOCKEN      = 1,
                    i_PLL0PD          = 0,
                    i_PLL0REFCLKSEL   = 0b001,
                    i_PLL0RESET       = self.reset,
                    o_PLL0LOCK        = self.lock,
                    o_PLL0OUTCLK      = self.clk,
                    o_PLL0OUTREFCLK   = self.refclk,

                    # pll1 (not used: power down)
                    i_PLL1PD          = 1,
                )
            else:
                gtpe2_common_params.update(
                    # pll0 (not used: power down)
                    i_PLL0PD          = 1,

                    # pll0
                    p_PLL1_FBDIV      = config["n2"],
                    p_PLL1_FBDIV_45   = config["n1"],
                    p_PLL1_REFCLK_DIV = config["m"],
                    i_PLL1LOCKEN      = 1,
                    i_PLL1PD          = 0,
                    i_PLL1REFCLKSEL   = 0b001,
                    i_PLL1RESET       = self.reset,
                    o_PLL1LOCK        = self.lock,
                    o_PLL1OUTCLK      = self.clk,
                    o_PLL1OUTREFCLK   = self.refclk,
                )

            m.submodules.gtpe2_common = Instance("GTPE2_COMMON", **gtpe2_common_params)
        else:
            self.gtrefclk  = self.refclk
            self.gtgrefclk = 0
            self.refclksel = 0b010

        return m

    @staticmethod
    def compute_config(refclk_freq, linerate):
        for n1 in [4, 5]:
            for n2 in [1, 2, 3, 4, 5]:
                for m in [1, 2]:
                    vco_freq = refclk_freq*(n1*n2)/m
                    if 1.6e9 <= vco_freq <= 3.3e9:
                        for d in [1, 2, 4, 8, 16]:
                            current_linerate = vco_freq*2/d
                            if current_linerate == linerate:
                                return {"n1": n1, "n2": n2, "m": m, "d": d,
                                        "vco_freq": vco_freq,
                                        "clkin": refclk_freq,
                                        "linerate": linerate}
        msg = "No config found for {:3.2f} MHz refclk / {:3.2f} Gbps linerate."
        raise ValueError(msg.format(refclk_freq/1e6, linerate/1e9))

    def __repr__(self):
        config = self.config
        r = """
GTPQuadPLL
==============
  overview:
  ---------
       +--------------------------------------------------+
       |                                                  |
       |   +-----+  +---------------------------+ +-----+ |
       |   |     |  | Phase Frequency Detector  | |     | |
CLKIN +----> /M  +-->       Charge Pump         +-> VCO +---> CLKOUT
       |   |     |  |       Loop Filter         | |     | |
       |   +-----+  +---------------------------+ +--+--+ |
       |              ^                              |    |
       |              |    +-------+    +-------+    |    |
       |              +----+  /N2  <----+  /N1  <----+    |
       |                   +-------+    +-------+         |
       +--------------------------------------------------+
                            +-------+
                   CLKOUT +->  2/D  +-> LINERATE
                            +-------+
  config:
  -------
    CLKIN    = {clkin}MHz
    CLKOUT   = CLKIN x (N1 x N2) / M = {clkin}MHz x ({n1} x {n2}) / {m}
             = {vco_freq}GHz
    LINERATE = CLKOUT x 2 / D = {vco_freq}GHz x 2 / {d}
             = {linerate}GHz
""".format(clkin    = config["clkin"]/1e6,
           n1       = config["n1"],
           n2       = config["n2"],
           m        = config["m"],
           vco_freq = config["vco_freq"]/1e9,
           d        = config["d"],
           linerate = config["linerate"]/1e9)
        return r

# GTP ----------------------------------------------------------------------------------------------

class GTP(Elaboratable):
    def __init__(self, qpll, tx_pads, rx_pads, sys_clk_freq,
        data_width          = 20,
        tx_buffer_enable    = False,
        rx_buffer_enable    = False,
        tx_polarity         = 0,
        rx_polarity         = 0,
        debug=None):

        assert data_width in [20]

        self.qpll = qpll
        self.sys_clk_freq = sys_clk_freq

        self.data_width = data_width
        self.tx_buffer_enable = tx_buffer_enable
        self.rx_buffer_enable = rx_buffer_enable
        self.rx_polarity = rx_polarity
        self.tx_polarity = tx_polarity

        self.rx_pads = rx_pads
        self.tx_pads = tx_pads

        # TX controls
        self.tx_enable              = Signal(reset=1)
        self.tx_ready               = Signal()
        self.tx_inhibit             = Signal()
        self.tx_produce_square_wave = Signal()
        self.tx_produce_pattern     = Signal()
        self.tx_pattern             = Signal(data_width)
        self.tx_prbs_config         = Signal(2)

        # RX controls
        self.rx_enable      = Signal(reset=1)
        self.rx_ready       = Signal()
        self.rx_align       = Signal(reset=1)
        self.rx_prbs_config = Signal(2)
        self.rx_prbs_pause  = Signal()
        self.rx_prbs_errors = Signal(32)

        self.drp_clk = Signal()
        self.drp_en = Signal()
        self.drp_we = Signal()
        self.drp_rdy = Signal()
        self.drp_addr = Signal(9)
        self.drp_di = Signal(16)
        self.drp_do = Signal(16)

        # Loopback
        self.loopback = Signal(3)

        self.tx_init = tx_init = GTPTXInit(self.sys_clk_freq, buffer_enable=self.tx_buffer_enable)

        self.rxdata = Signal(self.data_width)

        self.debug = debug
        self.cdr_hold = Signal()

    def elaborate(self, platform):
        # # #
        m = Module()

        rx_clock = Signal()
        m.domains += ClockDomain("rx")
        m.d.comb += ClockSignal("rx").eq(rx_clock)

        tx_clock = Signal()
        m.domains += ClockDomain("tx")
        m.d.comb += ClockSignal("tx").eq(tx_clock)

        self.nwords = nwords = self.data_width//10

        #m.submodules.encoder = ClockDomainsRenamer("tx")(Encoder(nwords))
        #self.decoders = [ClockDomainsRenamer("rx")(Decoder(True)) for _ in range(nwords)]
        #m.submodules += self.decoders

        m.d.comb += self.cdr_hold.eq(1)

        # Transceiver direct clock outputs (useful to specify clock constraints)
        self.txoutclk = Signal()
        self.rxoutclk = Signal()

        m.submodules += Instance("BUFG",
            i_I = self.txoutclk,
            o_O = tx_clock,
        )

        m.submodules += Instance("BUFG",
            i_I = self.rxoutclk,
            o_O = rx_clock,
        )

        self.tx_clk_freq = self.qpll.config["linerate"]/self.data_width
        self.rx_clk_freq = self.qpll.config["linerate"]/self.data_width

        # # #

        assert self.qpll.config["linerate"] < 6.6e9
        rxcdr_cfgs = {
            1 : 0x0000107FE406001041010,
            2 : 0x0000107FE206001041010,
            4 : 0x0000107FE106001041010,
            8 : 0x0000107FE086001041010,
           16 : 0x0000107FE086001041010,
        }

        # TX init ----------------------------------------------------------------------------------
        m.submodules.tx_init = tx_init = self.tx_init
        m.d.comb += [
            self.tx_ready.eq(tx_init.done),
            tx_init.restart.eq(~self.tx_enable)
        ]

        # RX init ----------------------------------------------------------------------------------
        m.submodules.rx_init = rx_init = GTPRXInit(self.sys_clk_freq, buffer_enable=self.rx_buffer_enable)
        m.d.comb += [
            self.rx_ready.eq(rx_init.done),
            rx_init.restart.eq(~self.rx_enable),

            self.drp_clk.eq(rx_init.drp_clk),
            self.drp_en.eq(rx_init.drp_en),
            self.drp_we.eq(rx_init.drp_we),
            rx_init.drp_rdy.eq(self.drp_rdy),
            self.drp_addr.eq(rx_init.drp_addr),
            self.drp_di.eq(rx_init.drp_di),
            rx_init.drp_do.eq(self.drp_do),
        ]


        # PLL --------------------------------------------------------------------------------------
        m.d.comb += [
            tx_init.plllock.eq(self.qpll.lock),
            rx_init.plllock.eq(self.qpll.lock),
            self.qpll.reset.eq(tx_init.pllreset)
        ]

        # GTPE2_CHANNEL instance -------------------------------------------------------------------
        class Open(Signal): pass

        txdata = Signal(self.data_width)
        rxdata = self.rxdata

        m.d.sync += txdata.eq(0b0) #11001100110011001100) #txdata + 1)

        rxphaligndone = Signal()
        self.gtp_params = dict(
            # Simulation-Only Attributes
            p_SIM_RECEIVER_DETECT_PASS   = "TRUE",
            p_SIM_TX_EIDLE_DRIVE_LEVEL   = "X",
            p_SIM_RESET_SPEEDUP          = "FALSE",
            p_SIM_VERSION                = "2.0",

            # RX Byte and Word Alignment Attributes
            p_ALIGN_COMMA_DOUBLE         = "FALSE",
            p_ALIGN_COMMA_ENABLE         = 0b1111111111,
            p_ALIGN_COMMA_WORD           = 2 if self.data_width == 20 else 4,
            p_ALIGN_MCOMMA_DET           = "TRUE",
            p_ALIGN_MCOMMA_VALUE         = 0b1010000011,
            p_ALIGN_PCOMMA_DET           = "TRUE",
            p_ALIGN_PCOMMA_VALUE         = 0b0101111100,
            p_SHOW_REALIGN_COMMA         = "TRUE",
            p_RXSLIDE_AUTO_WAIT          = 7,
            p_RXSLIDE_MODE               = "OFF" if self.rx_buffer_enable else "PCS",
            p_RX_SIG_VALID_DLY           = 10,

            # RX 8B/10B Decoder Attributes
            p_RX_DISPERR_SEQ_MATCH       = "TRUE",
            p_DEC_MCOMMA_DETECT          = "TRUE",
            p_DEC_PCOMMA_DETECT          = "TRUE",
            p_DEC_VALID_COMMA_ONLY       = "TRUE",

            # RX Clock Correction Attributes
            p_CBCC_DATA_SOURCE_SEL       = "DECODED",
            p_CLK_COR_SEQ_2_USE          = "FALSE",
            p_CLK_COR_KEEP_IDLE          = "FALSE",
            p_CLK_COR_MAX_LAT            = 10 if self.data_width == 20 else 19,
            p_CLK_COR_MIN_LAT            = 8 if self.data_width == 20 else 15,
            p_CLK_COR_PRECEDENCE         = "TRUE",
            p_CLK_COR_REPEAT_WAIT        = 0,
            p_CLK_COR_SEQ_LEN            = 1,
            p_CLK_COR_SEQ_1_ENABLE       = 0b1111,
            p_CLK_COR_SEQ_1_1            = 0b0100000000,
            p_CLK_COR_SEQ_1_2            = 0b0000000000,
            p_CLK_COR_SEQ_1_3            = 0b0000000000,
            p_CLK_COR_SEQ_1_4            = 0b0000000000,
            p_CLK_CORRECT_USE            = "FALSE",
            p_CLK_COR_SEQ_2_ENABLE       = 0b1111,
            p_CLK_COR_SEQ_2_1            = 0b0100000000,
            p_CLK_COR_SEQ_2_2            = 0b0000000000,
            p_CLK_COR_SEQ_2_3            = 0b0000000000,
            p_CLK_COR_SEQ_2_4            = 0b0000000000,

            # RX Channel Bonding Attributes
            p_CHAN_BOND_KEEP_ALIGN       = "FALSE",
            p_CHAN_BOND_MAX_SKEW         = 1,
            p_CHAN_BOND_SEQ_LEN          = 1,
            p_CHAN_BOND_SEQ_1_1          = 0b0000000000,
            p_CHAN_BOND_SEQ_1_2          = 0b0000000000,
            p_CHAN_BOND_SEQ_1_3          = 0b0000000000,
            p_CHAN_BOND_SEQ_1_4          = 0b0000000000,
            p_CHAN_BOND_SEQ_1_ENABLE     = 0b1111,
            p_CHAN_BOND_SEQ_2_1          = 0b0000000000,
            p_CHAN_BOND_SEQ_2_2          = 0b0000000000,
            p_CHAN_BOND_SEQ_2_3          = 0b0000000000,
            p_CHAN_BOND_SEQ_2_4          = 0b0000000000,
            p_CHAN_BOND_SEQ_2_ENABLE     = 0b1111,
            p_CHAN_BOND_SEQ_2_USE        = "FALSE",
            p_FTS_DESKEW_SEQ_ENABLE      = 0b1111,
            p_FTS_LANE_DESKEW_CFG        = 0b1111,
            p_FTS_LANE_DESKEW_EN         = "FALSE",

            # RX Margin Analysis Attributes
            p_ES_CONTROL                 = 0b000000,
            p_ES_ERRDET_EN               = "FALSE",
            p_ES_EYE_SCAN_EN             = "TRUE",
            p_ES_HORZ_OFFSET             = 0x000,
            p_ES_PMA_CFG                 = 0b0000000000,
            p_ES_PRESCALE                = 0b00000,
            p_ES_QUALIFIER               = 0x00000000000000000000,
            p_ES_QUAL_MASK               = 0x00000000000000000000,
            p_ES_SDATA_MASK              = 0x00000000000000000000,
            p_ES_VERT_OFFSET             = 0b000000000,

            # FPGA RX Interface Attributes
            p_RX_DATA_WIDTH              = self.data_width,

            # PMA Attributes
            p_OUTREFCLK_SEL_INV          = 0b11,
            p_PMA_RSV                    = 0x00000333,
            p_PMA_RSV2                   = 0x00002040,
            p_PMA_RSV3                   = 0b00,
            p_PMA_RSV4                   = 0b0000,
            p_RX_BIAS_CFG                = 0b0000111100110011,
            p_DMONITOR_CFG               = 0x000A00,
            p_RX_CM_SEL                  = 0b01,
            p_RX_CM_TRIM                 = 0b0000,
            p_RX_DEBUG_CFG               = 0b00000000000000,
            p_RX_OS_CFG                  = 0b0000010000000,
            p_TERM_RCAL_CFG              = 0b100001000010000,
            p_TERM_RCAL_OVRD             = 0b000,
            p_TST_RSV                    = 0x00000000,
            p_RX_CLK25_DIV               = 5,
            p_TX_CLK25_DIV               = 5,
            p_UCODEER_CLR                = 0b0,

            # PCI Express Attributes
            p_PCS_PCIE_EN                = "FALSE",

            # PCS Attributes
            p_PCS_RSVD_ATTR              = 0x000000000000,

            # RX Buffer Attributes
            p_RXBUF_ADDR_MODE            = "FAST",
            p_RXBUF_EIDLE_HI_CNT         = 0b1000,
            p_RXBUF_EIDLE_LO_CNT         = 0b0000,
            p_RXBUF_EN                   = "TRUE" if self.rx_buffer_enable else "FALSE",
            p_RX_BUFFER_CFG              = 0b000000,
            p_RXBUF_RESET_ON_CB_CHANGE   = "TRUE",
            p_RXBUF_RESET_ON_COMMAALIGN  = "FALSE",
            p_RXBUF_RESET_ON_EIDLE       = "FALSE",
            p_RXBUF_RESET_ON_RATE_CHANGE = "TRUE",
            p_RXBUFRESET_TIME            = 0b00001,
            p_RXBUF_THRESH_OVFLW         = 61,
            p_RXBUF_THRESH_OVRD          = "FALSE",
            p_RXBUF_THRESH_UNDFLW        = 4,
            p_RXDLY_CFG                  = 0x001F,
            p_RXDLY_LCFG                 = 0x030,
            p_RXDLY_TAP_CFG              = 0x0000,
            p_RXPH_CFG                   = 0xC00002,
            p_RXPHDLY_CFG                = 0x084020,
            p_RXPH_MONITOR_SEL           = 0b00000,
            p_RX_XCLK_SEL                = "RXREC" if self.rx_buffer_enable else "RXUSR",
            p_RX_DDI_SEL                 = 0b000000,
            p_RX_DEFER_RESET_BUF_EN      = "TRUE",

            # CDR Attributes
            p_RXCDR_CFG                  = rxcdr_cfgs[self.qpll.config["d"]],
            p_RXCDR_FR_RESET_ON_EIDLE    = 0b0,
            p_RXCDR_HOLD_DURING_EIDLE    = 0b0,
            p_RXCDR_PH_RESET_ON_EIDLE    = 0b0,
            p_RXCDR_LOCK_CFG             = 0b001001,

            # RX Initialization and Reset Attributes
            p_RXCDRFREQRESET_TIME        = 0b00001,
            p_RXCDRPHRESET_TIME          = 0b00001,
            p_RXISCANRESET_TIME          = 0b00001,
            p_RXPCSRESET_TIME            = 0b00001,
            p_RXPMARESET_TIME            = 0b00011,

            # RX OOB Signaling Attributes
            p_RXOOB_CFG                  = 0b0000110,

            # RX Gearbox Attributes
            p_RXGEARBOX_EN               = "FALSE",
            p_GEARBOX_MODE               = 0b000,

            # PRBS Detection Attribute
            p_RXPRBS_ERR_LOOPBACK        = 0b0,

            # Power-Down Attributes
            p_PD_TRANS_TIME_FROM_P2      = 0x03c,
            p_PD_TRANS_TIME_NONE_P2      = 0x3c,
            p_PD_TRANS_TIME_TO_P2        = 0x64,

            # RX OOB Signaling Attributes
            p_SAS_MAX_COM                = 64,
            p_SAS_MIN_COM                = 36,
            p_SATA_BURST_SEQ_LEN         = 0b0101,
            p_SATA_BURST_VAL             = 0b100,
            p_SATA_EIDLE_VAL             = 0b100,
            p_SATA_MAX_BURST             = 8,
            p_SATA_MAX_INIT              = 21,
            p_SATA_MAX_WAKE              = 7,
            p_SATA_MIN_BURST             = 4,
            p_SATA_MIN_INIT              = 12,
            p_SATA_MIN_WAKE              = 4,

            # RX Fabric Clock Output Control Attributes
            p_TRANS_TIME_RATE            = 0x0E,

            # TX Buffer Attributes
            p_TXBUF_EN                   = "TRUE" if self.tx_buffer_enable else "FALSE",
            p_TXBUF_RESET_ON_RATE_CHANGE = "TRUE",
            p_TXDLY_CFG                  = 0x001F,
            p_TXDLY_LCFG                 = 0x030,
            p_TXDLY_TAP_CFG              = 0x0000,
            p_TXPH_CFG                   = 0x0780,
            p_TXPHDLY_CFG                = 0x084020,
            p_TXPH_MONITOR_SEL           = 0b00000,
            p_TX_XCLK_SEL                = "TXOUT" if self.tx_buffer_enable else "TXUSR",

            # FPGA TX Interface Attributes
            p_TX_DATA_WIDTH              = self.data_width,

            # TX Configurable Driver Attributes
            p_TX_DEEMPH0                 = 0b000000,
            p_TX_DEEMPH1                 = 0b000000,
            p_TX_EIDLE_ASSERT_DELAY      = 0b110,
            p_TX_EIDLE_DEASSERT_DELAY    = 0b100,
            p_TX_LOOPBACK_DRIVE_HIZ      = "FALSE",
            p_TX_MAINCURSOR_SEL          = 0b0,
            p_TX_DRIVE_MODE              = "DIRECT",
            p_TX_MARGIN_FULL_0           = 0b1001110,
            p_TX_MARGIN_FULL_1           = 0b1001001,
            p_TX_MARGIN_FULL_2           = 0b1000101,
            p_TX_MARGIN_FULL_3           = 0b1000010,
            p_TX_MARGIN_FULL_4           = 0b1000000,
            p_TX_MARGIN_LOW_0            = 0b1000110,
            p_TX_MARGIN_LOW_1            = 0b1000100,
            p_TX_MARGIN_LOW_2            = 0b1000010,
            p_TX_MARGIN_LOW_3            = 0b1000000,
            p_TX_MARGIN_LOW_4            = 0b1000000,

            # TX Gearbox Attributes
            p_TXGEARBOX_EN               = "FALSE",

            # TX Initialization and Reset Attributes
            p_TXPCSRESET_TIME            = 0b00001,
            p_TXPMARESET_TIME            = 0b00001,

            # TX Receiver Detection Attributes
            p_TX_RXDETECT_CFG            = 0x1832,
            p_TX_RXDETECT_REF            = 0b100,

            # JTAG Attributes
            p_ACJTAG_DEBUG_MODE          = 0b0,
            p_ACJTAG_MODE                = 0b0,
            p_ACJTAG_RESET               = 0b0,

            # CDR Attributes
            p_CFOK_CFG                   = 0x49000040E80,
            p_CFOK_CFG2                  = 0b0100000,
            p_CFOK_CFG3                  = 0b0100000,
            p_CFOK_CFG4                  = 0b0,
            p_CFOK_CFG5                  = 0x0,
            p_CFOK_CFG6                  = 0b0000,
            p_RXOSCALRESET_TIME          = 0b00011,
            p_RXOSCALRESET_TIMEOUT       = 0b00000,

            # PMA Attributes
            p_CLK_COMMON_SWING           = 0b0,
            p_RX_CLKMUX_EN               = 0b1,
            p_TX_CLKMUX_EN               = 0b1,
            p_ES_CLK_PHASE_SEL           = 0b0,
            p_USE_PCS_CLK_PHASE_SEL      = 0b0,
            p_PMA_RSV6                   = 0b0,
            p_PMA_RSV7                   = 0b0,

            # TX Configuration Driver Attributes
            p_TX_PREDRIVER_MODE          = 0b0,
            p_PMA_RSV5                   = 0b0,
            p_SATA_PLL_CFG               = "VCO_3000MHZ",

            # RX Fabric Clock Output Control Attributes
            p_RXOUT_DIV                  = self.qpll.config["d"],

            # TX Fabric Clock Output Control Attributes
            p_TXOUT_DIV                  = self.qpll.config["d"],

            # RX Phase Interpolator Attributes
            p_RXPI_CFG0                  = 0b000,
            p_RXPI_CFG1                  = 0b1,
            p_RXPI_CFG2                  = 0b1,

            # RX Equalizer Attributes
            p_ADAPT_CFG0                 = 0x00000,
            p_RXLPMRESET_TIME            = 0b0001111,
            p_RXLPM_BIAS_STARTUP_DISABLE = 0b0,
            p_RXLPM_CFG                  = 0b0110,
            p_RXLPM_CFG1                 = 0b0,
            p_RXLPM_CM_CFG               = 0b0,
            p_RXLPM_GC_CFG               = 0b111100010,
            p_RXLPM_GC_CFG2              = 0b001,
            p_RXLPM_HF_CFG               = 0b00001111110000,
            p_RXLPM_HF_CFG2              = 0b01010,
            p_RXLPM_HF_CFG3              = 0b0000,
            p_RXLPM_HOLD_DURING_EIDLE    = 0b0,
            p_RXLPM_INCM_CFG             = 0b0,
            p_RXLPM_IPCM_CFG             = 0b1,
            p_RXLPM_LF_CFG               = 0b000000001111110000,
            p_RXLPM_LF_CFG2              = 0b01010,
            p_RXLPM_OSINT_CFG            = 0b100,

            # TX Phase Interpolator PPM Controller Attributes
            p_TXPI_CFG0                  = 0b00,
            p_TXPI_CFG1                  = 0b00,
            p_TXPI_CFG2                  = 0b00,
            p_TXPI_CFG3                  = 0b0,
            p_TXPI_CFG4                  = 0b0,
            p_TXPI_CFG5                  = 0b000,
            p_TXPI_GREY_SEL              = 0b0,
            p_TXPI_INVSTROBE_SEL         = 0b0,
            p_TXPI_PPMCLK_SEL            = "TXUSRCLK2",
            p_TXPI_PPM_CFG               = 0x00,
            p_TXPI_SYNFREQ_PPM           = 0b001,

            # LOOPBACK Attributes
            p_LOOPBACK_CFG               = 0b0,
            p_PMA_LOOPBACK_CFG           = 0b0,

            # RX OOB Signalling Attributes
            p_RXOOB_CLK_CFG              = "PMA",

            # TX OOB Signalling Attributes
            p_TXOOB_CFG                  = 0b0,

            # RX Buffer Attributes
            p_RXSYNC_MULTILANE           = 0b0,
            p_RXSYNC_OVRD                = 0b0,
            p_RXSYNC_SKIP_DA             = 0b0,

            # TX Buffer Attributes
            p_TXSYNC_MULTILANE           = 0b0,
            p_TXSYNC_OVRD                = 0b1 if self.tx_buffer_enable else 0b0,
            p_TXSYNC_SKIP_DA             = 0b0
        )

        pmadone = Signal()

        if False:
            m.d.comb += [
                self.debug[0].eq(tx_init.gttxreset),
                self.debug[1].eq(tx_init.txuserrdy),
                self.debug[2].eq(tx_init.txresetdone),
                self.debug[3].eq(tx_init.plllock),
                self.debug[4].eq(tx_init.init_delay.wait),
                self.debug[5].eq(pmadone),
            ]
        else:
            m.d.comb += [
                self.debug[0].eq(rx_init.gtrxreset),
                self.debug[1].eq(rx_init.rxuserrdy),
                self.debug[2].eq(rx_init.rxresetdone),
                self.debug[3].eq(rx_init.plllock),
                self.debug[4].eq(rx_init.rxpmaresetdone),
                self.debug[5].eq(rx_init.drp_rdy),
            ]

        self.gtp_params.update(
            # CPLL Ports
            i_GTRSVD               = 0b0000000000000000,
            i_PCSRSVDIN            = 0b0000000000000000,
            i_TSTIN                = 0b11111111111111111111,

            # Clocking Ports
            i_RXSYSCLKSEL          = 0b00 if self.qpll.channel == 0 else 0b11,
            i_TXSYSCLKSEL          = 0b00 if self.qpll.channel == 0 else 0b11,

            # DRP (Dynamic Reconfiguration Ports)
            i_DRPADDR              = self.drp_addr,
            i_DRPCLK               = self.drp_clk,
            i_DRPDI                = self.drp_di,
            o_DRPDO                = self.drp_do,
            i_DRPEN                = self.drp_en,
            o_DRPRDY               = self.drp_rdy,
            i_DRPWE                = self.drp_we,

            # FPGA TX Interface Datapath Configuration
            i_TX8B10BEN            = 0,

            # GTPE2_CHANNEL Clocking Ports
            i_PLL0CLK              = self.qpll.clk if self.qpll.channel == 0 else 0,
            i_PLL0REFCLK           = self.qpll.refclk if self.qpll.channel == 0 else 0,
            i_PLL1CLK              = self.qpll.clk if self.qpll.channel == 1 else 0,
            i_PLL1REFCLK           = self.qpll.refclk if self.qpll.channel == 1 else 0,

            # Loopback Ports
            i_LOOPBACK             = self.loopback,

            # PCI Express Ports
            o_PHYSTATUS            = Open(),
            i_RXRATE               = 0,
            o_RXVALID              = Open(),

            # PMA Reserved Ports
            i_PMARSVDIN3           = 0b0,
            i_PMARSVDIN4           = 0b0,

            # Power-Down Ports
            i_RXPD                 = Cat(rx_init.gtrxpd, rx_init.gtrxpd),
            i_TXPD                 = 0b00,

            # RX 8B/10B Decoder Ports
            i_SETERRSTATUS         = 0,

            # RX Initialization and Reset Ports
            i_EYESCANRESET         = 0,
            i_RXUSERRDY            = rx_init.rxuserrdy,

            # RX Margin Analysis Ports
            o_EYESCANDATAERROR     = Open(),
            i_EYESCANMODE          = 0,
            i_EYESCANTRIGGER       = 0,

            # Receive Ports
            i_CLKRSVD0             = 0,
            i_CLKRSVD1             = 0,
            i_DMONFIFORESET        = 0,
            i_DMONITORCLK          = 0,
            o_RXPMARESETDONE       = rx_init.rxpmaresetdone,
            i_SIGVALIDCLK          = 0,

            # Receive Ports - CDR Ports
            i_RXCDRFREQRESET       = 0,
            i_RXCDRHOLD            = self.cdr_hold,
            o_RXCDRLOCK            = Open(),
            i_RXCDROVRDEN          = 0,
            i_RXCDRRESET           = 0,
            i_RXCDRRESETRSV        = 0,
            i_RXOSCALRESET         = 0,
            i_RXOSINTCFG           = 0b0010,
            o_RXOSINTDONE          = Open(),
            i_RXOSINTHOLD          = 0,
            i_RXOSINTOVRDEN        = 0,
            i_RXOSINTPD            = 0,
            o_RXOSINTSTARTED       = Open(),
            i_RXOSINTSTROBE        = 0,
            o_RXOSINTSTROBESTARTED = Open(),
            i_RXOSINTTESTOVRDEN    = 0,

            # Receive Ports - Clock Correction Ports
            o_RXCLKCORCNT          = Open(),

            # Receive Ports - FPGA RX Interface Datapath Configuration
            i_RX8B10BEN            = 0,

            # Receive Ports - FPGA RX Interface Ports
            o_RXDATA               = Cat(*[rxdata[10*i:10*i+8] for i in range(nwords)]),
            i_RXUSRCLK             = rx_clock,
            i_RXUSRCLK2            = rx_clock,

            # Receive Ports - Pattern Checker Ports
            o_RXPRBSERR            = Open(),
            i_RXPRBSSEL            = 0,

            # Receive Ports - Pattern Checker ports
            i_RXPRBSCNTRESET       = 0,

            # Receive Ports - RX 8B/10B Decoder Ports
            o_RXCHARISCOMMA        = Open(),
            o_RXCHARISK            = Cat(*[rxdata[10*i+8] for i in range(nwords)]),
            o_RXDISPERR            = Cat(*[rxdata[10*i+9] for i in range(nwords)]),
            o_RXNOTINTABLE         = Open(),

            # Receive Ports - RX AFE Ports
            i_GTPRXN               = self.rx_pads[0],
            i_GTPRXP               = self.rx_pads[1],
            i_PMARSVDIN2           = 0b0,
            o_PMARSVDOUT0          = Open(),
            o_PMARSVDOUT1          = Open(),

            # Receive Ports - RX Buffer Bypass Ports
            i_RXBUFRESET           = 0,
            o_RXBUFSTATUS          = Open(),
            i_RXDDIEN              = 0 if self.rx_buffer_enable else 1,
            i_RXDLYBYPASS          = 1 if self.rx_buffer_enable else 0,
            i_RXDLYEN              = 0,
            i_RXDLYOVRDEN          = 0,
            i_RXDLYSRESET          = rx_init.rxdlysreset,
            o_RXDLYSRESETDONE      = rx_init.rxdlysresetdone,
            i_RXPHALIGN            = 0,
            o_RXPHALIGNDONE        = rxphaligndone,
            i_RXPHALIGNEN          = 0,
            i_RXPHDLYPD            = 0,
            i_RXPHDLYRESET         = 0,
            o_RXPHMONITOR          = Open(),
            i_RXPHOVRDEN           = 0,
            o_RXPHSLIPMONITOR      = Open(),
            o_RXSTATUS             = Open(),
            i_RXSYNCALLIN          = rxphaligndone,
            o_RXSYNCDONE           = rx_init.rxsyncdone,
            i_RXSYNCIN             = 0,
            i_RXSYNCMODE           = 0 if self.rx_buffer_enable else 1,
            o_RXSYNCOUT            = Open(),

            # Receive Ports - RX Byte and Word Alignment Ports
            o_RXBYTEISALIGNED      = Open(),
            o_RXBYTEREALIGN        = Open(),
            o_RXCOMMADET           = Open(),
            i_RXCOMMADETEN         = 0,
            i_RXMCOMMAALIGNEN      = 0,
            i_RXPCOMMAALIGNEN      = 0,
            i_RXSLIDE              = 0,

            # Receive Ports - RX Channel Bonding Ports
            o_RXCHANBONDSEQ        = Open(),
            i_RXCHBONDEN           = 0,
            i_RXCHBONDI            = 0b0000,
            i_RXCHBONDLEVEL        = 0,
            i_RXCHBONDMASTER       = 0,
            o_RXCHBONDO            = Open(),
            i_RXCHBONDSLAVE        = 0,

            # Receive Ports - RX Channel Bonding Ps
            o_RXCHANISALIGNED      = Open(),
            o_RXCHANREALIGN        = Open(),

            # Receive Ports - RX Decision Feedback Equalizer
            o_DMONITOROUT          = Open(),
            i_RXADAPTSELTEST       = 0,
            i_RXDFEXYDEN           = 0,
            i_RXOSINTEN            = 0b1,
            i_RXOSINTID0           = 0,
            i_RXOSINTNTRLEN        = 0,
            o_RXOSINTSTROBEDONE    = Open(),

            # Receive Ports - RX Driver,OOB signalling,Coupling and Eq.,CDR
            i_RXLPMLFOVRDEN        = 0,
            i_RXLPMOSINTNTRLEN     = 0,

            # Receive Ports - RX Equalizer Ports
            i_RXLPMHFHOLD          = 0,
            i_RXLPMHFOVRDEN        = 0,
            i_RXLPMLFHOLD          = 0,
            i_RXOSHOLD             = 0,
            i_RXOSOVRDEN           = 0,

            # Receive Ports - RX Fabric ClocK Output Control Ports
            o_RXRATEDONE           = Open(),

            # Receive Ports - RX Fabric Clock Output Control Ports
            i_RXRATEMODE           = 0b0,

            # Receive Ports - RX Fabric Output Control Ports
            o_RXOUTCLK             = self.rxoutclk,
            o_RXOUTCLKFABRIC       = Open(),
            o_RXOUTCLKPCS          = Open(),
            i_RXOUTCLKSEL          = 0b010,

            # Receive Ports - RX Gearbox Ports
            o_RXDATAVALID          = Open(),
            o_RXHEADER             = Open(),
            o_RXHEADERVALID        = Open(),
            o_RXSTARTOFSEQ         = Open(),
            i_RXGEARBOXSLIP        = 0,

            # Receive Ports - RX Initialization and Reset Ports
            i_GTRXRESET            = rx_init.gtrxreset,
            i_RXLPMRESET           = 0,
            i_RXOOBRESET           = 0,
            i_RXPCSRESET           = 0,
            i_RXPMARESET           = 0,

            # Receive Ports - RX OOB Signaling ports
            o_RXCOMSASDET          = Open(),
            o_RXCOMWAKEDET         = Open(),
            o_RXCOMINITDET         = Open(),
            o_RXELECIDLE           = Open(),
            i_RXELECIDLEMODE       = 0b11,

            # Receive Ports - RX Polarity Control Ports
            i_RXPOLARITY           = self.rx_polarity,

            # Receive Ports -RX Initialization and Reset Ports
            o_RXRESETDONE          = rx_init.rxresetdone,

            # TX Buffer Bypass Ports
            i_TXPHDLYTSTCLK        = 0,

            # TX Configurable Driver Ports
            i_TXPOSTCURSOR         = 0b00000,
            i_TXPOSTCURSORINV      = 0,
            i_TXPRECURSOR          = 0b00000,
            i_TXPRECURSORINV       = 0,

            # TX Fabric Clock Output Control Ports
            i_TXRATEMODE           = 0,

            # TX Initialization and Reset Ports
            i_CFGRESET             = 0,
            i_GTTXRESET            = tx_init.gttxreset,
            o_PCSRSVDOUT           = Open(),
            i_TXUSERRDY            = tx_init.txuserrdy,

            # TX Phase Interpolator PPM Controller Ports
            i_TXPIPPMEN            = 0,
            i_TXPIPPMOVRDEN        = 0,
            i_TXPIPPMPD            = 0,
            i_TXPIPPMSEL           = 1,
            i_TXPIPPMSTEPSIZE      = 0,

            # Transceiver Reset Mode Operation
            i_GTRESETSEL           = 0,
            i_RESETOVRD            = 0,

            # Transmit Ports
            o_TXPMARESETDONE       = pmadone, #self.debug[3],

            # Transmit Ports - Configurable Driver Ports
            i_PMARSVDIN0           = 0b0,
            i_PMARSVDIN1           = 0b0,

            # Transmit Ports - FPGA TX Interface Ports
            i_TXDATA               = Cat(*[txdata[10*i:10*i+8] for i in range(nwords)]),
            i_TXUSRCLK             = tx_clock,
            i_TXUSRCLK2            = tx_clock,

            # Transmit Ports - PCI Express Ports
            i_TXELECIDLE           = 0,
            i_TXMARGIN             = 0,
            i_TXRATE               = 0,
            i_TXSWING              = 0,

            # Transmit Ports - Pattern Generator Ports
            i_TXPRBSFORCEERR       = 0,

            # Transmit Ports - TX 8B/10B Encoder Ports
            i_TX8B10BBYPASS        = 0,
            i_TXCHARDISPMODE       = Cat(*[txdata[10*i+9] for i in range(nwords)]),
            i_TXCHARDISPVAL        = Cat(*[txdata[10*i+8] for i in range(nwords)]),
            i_TXCHARISK            = 0,

            # Transmit Ports - TX Buffer Bypass Ports
            i_TXDLYBYPASS          = 1 if self.tx_buffer_enable else 0,
            i_TXDLYEN              = 0 if self.tx_buffer_enable else tx_init.txdlyen,
            i_TXDLYHOLD            = 0,
            i_TXDLYOVRDEN          = 0,
            i_TXDLYSRESET          = tx_init.txdlysreset,
            o_TXDLYSRESETDONE      = tx_init.txdlysresetdone,
            i_TXDLYUPDOWN          = 0,
            i_TXPHALIGN            = tx_init.txphalign,
            o_TXPHALIGNDONE        = tx_init.txphaligndone,
            i_TXPHALIGNEN          = 0 if self.tx_buffer_enable else 1,
            i_TXPHDLYPD            = 0,
            i_TXPHDLYRESET         = 0,
            i_TXPHINIT             = tx_init.txphinit,
            o_TXPHINITDONE         = tx_init.txphinitdone,
            i_TXPHOVRDEN           = 0,

            # Transmit Ports - TX Buffer Ports
            o_TXBUFSTATUS          = Open(),

            # Transmit Ports - TX Buffer and Phase Alignment Ports
            i_TXSYNCALLIN          = 0,
            o_TXSYNCDONE           = Open(),
            i_TXSYNCIN             = 0,
            i_TXSYNCMODE           = 0,
            o_TXSYNCOUT            = Open(),

            # Transmit Ports - TX Configurable Driver Ports
            o_GTPTXN               = self.tx_pads[0],
            o_GTPTXP               = self.tx_pads[1],
            i_TXBUFDIFFCTRL        = 0b100,
            i_TXDEEMPH             = 0,
            i_TXDIFFCTRL           = 0b1000,
            i_TXDIFFPD             = 0,
            i_TXINHIBIT            = 0,
            i_TXMAINCURSOR         = 0b0000000,
            i_TXPISOPD             = 0,

            # Transmit Ports - TX Fabric Clock Output Control Ports
            o_TXOUTCLK             = self.txoutclk,
            o_TXOUTCLKFABRIC       = Open(),
            o_TXOUTCLKPCS          = Open(),
            i_TXOUTCLKSEL          = 0b010 if self.tx_buffer_enable else 0b011,
            o_TXRATEDONE           = Open(),

            # Transmit Ports - TX Gearbox Ports
            o_TXGEARBOXREADY       = Open(),
            i_TXHEADER             = 0,
            i_TXSEQUENCE           = 0,
            i_TXSTARTSEQ           = 0,

            # Transmit Ports - TX Initialization and Reset Ports
            i_TXPCSRESET           = 0,
            i_TXPMARESET           = 0,
            o_TXRESETDONE          = tx_init.txresetdone,

            # Transmit Ports - TX OOB signalling Ports
            o_TXCOMFINISH          = Open(),
            i_TXCOMINIT            = 0,
            i_TXCOMSAS             = 0,
            i_TXCOMWAKE            = 0,
            i_TXPDELECIDLEMODE     = 0,

            # Transmit Ports - TX Polarity Control Ports
            i_TXPOLARITY           = self.tx_polarity,

            # Transmit Ports - TX Receiver Detection Ports
            i_TXDETECTRX           = 0,

            # Transmit Ports - pattern Generator Ports
            i_TXPRBSSEL            = 0,
        )

        if False:
            # TX clocking ------------------------------------------------------------------------------
            tx_reset_deglitched = Signal()
            #tx_reset_deglitched.attr.add("no_retiming")
            m.d.sync += tx_reset_deglitched.eq(~tx_init.done)
            m.domains += ClockDomain('cd_tx')

            txoutclk_bufg = Signal()
            m.submodules += Instance("BUFG",
                i_I = self.txoutclk,
                o_O = txoutclk_bufg,
            )

            if not self.tx_buffer_enable:
                txoutclk_div = self.qpll.config["clkin"]/self.tx_clk_freq
            else:
                txoutclk_div = 1
            # Use txoutclk_bufg when divider is 1
            if txoutclk_div == 1:
                m.d.comb += ClockSignal('cd_tx').eq(txoutclk_bufg)
                m.submodules += ResetSynchronizer(domain='cd_tx', arst=tx_reset_deglitched)
            # Use a BUFR when integer divider (with BUFR_DIVIDE)
            elif txoutclk_div == int(txoutclk_div):
                txoutclk_bufr = Signal()
                m.submodules += [
                    Instance("BUFR",
                        p_BUFR_DIVIDE = str(int(txoutclk_div)),
                        i_CE = 1,
                        i_I  = txoutclk_bufg,
                        o_O  = txoutclk_bufr,
                    ),
                    Instance("BUFG",
                        i_I = txoutclk_bufr,
                        o_O = self.cd_tx.clk,
                    ),
                    ResetSynchronizer(domain='cd_tx', arst=tx_reset_deglitched)
                ]
            # Use a PLL when non-integer divider
            else:
                raise Exception("Non integer divider")

            # RX clocking ------------------------------------------------------------------------------
            rx_reset_deglitched = Signal()
            #rx_reset_deglitched.attr.add("no_retiming")
            m.d.cd_tx += rx_reset_deglitched.eq(~rx_init.done)
            m.domains += ClockDomain('cd_rx')
            m.submodules += [
                Instance("BUFG",
                    i_I = self.rxoutclk,
                    o_O = ClockSignal('cd_rx'),
                ),
                ResetSynchronizer(domain='cd_rx', arst=rx_reset_deglitched)
            ]

        m.submodules += Instance("GTPE2_CHANNEL", **self.gtp_params)

        return m

# GTP TX Init --------------------------------------------------------------------------------------

class GTPTXInit(Elaboratable):
    def __init__(self, sys_clk_freq, buffer_enable):
        self.sys_clk_freq = sys_clk_freq

        self.done            = Signal() # o
        self.restart         = Signal() # i

        # GTP signals
        self.plllock         = Signal() # i
        self.pllreset        = Signal() # o
        self.gttxreset       = Signal() # o
        self.gttxpd          = Signal() # o
        self.txresetdone     = Signal() # i
        self.txdlysreset     = Signal() # o
        self.txdlysresetdone = Signal() # i
        self.txphinit        = Signal() # o
        self.txphinitdone    = Signal() # i
        self.txphalign       = Signal() # o
        self.txphaligndone   = Signal() # i
        self.txdlyen         = Signal() # o
        self.txuserrdy       = Signal() # o

        # DRP (optional)
        self.drp_start       = Signal()        # o
        self.drp_done        = Signal(reset=1) # i

        self.init_delay = WaitTimer(int(1e-6*self.sys_clk_freq))
        print(self.init_delay.t, self.sys_clk_freq)
        self.debug = Signal()

    def elaborate(self, platform):
        m = Module()

        # Double-latch transceiver asynch outputs
        plllock         = Signal()
        txresetdone     = Signal()
        txdlysresetdone = Signal()
        txphinitdone    = Signal()
        txphaligndone   = Signal()
        m.submodules += [
            FFSynchronizer(self.plllock, plllock),
            FFSynchronizer(self.txresetdone, txresetdone),
            FFSynchronizer(self.txdlysresetdone, txdlysresetdone),
            FFSynchronizer(self.txphinitdone, txphinitdone),
            FFSynchronizer(self.txphaligndone, txphaligndone)
        ]

        # Deglitch FSM outputs driving transceiver asynch inputs
        gttxreset   = Signal()
        gttxpd      = Signal()
        txdlysreset = Signal()
        txphinit    = Signal()
        txphalign   = Signal()
        txdlyen     = Signal()
        txuserrdy   = Signal()
        m.d.sync += [
            self.gttxreset.eq(gttxreset),
            self.gttxpd.eq(gttxpd),
            self.txdlysreset.eq(txdlysreset),
            self.txphinit.eq(txphinit),
            self.txphalign.eq(txphalign),
            self.txdlyen.eq(txdlyen),
            self.txuserrdy.eq(txuserrdy)
        ]

        # Detect txphaligndone rising edge
        txphaligndone_r = Signal(reset=1)
        txphaligndone_rising = Signal()
        m.d.sync += txphaligndone_r.eq(txphaligndone)
        m.d.comb += txphaligndone_rising.eq(txphaligndone & ~txphaligndone_r)

        # Wait 500ns after configuration before releasing GTP reset (to follow AR43482)
        m.submodules.init_delay = init_delay = self.init_delay

        with m.FSM(reset="POWER-DOWN") as fsm:
            with m.State("POWER-DOWN"):
                m.d.comb += [
                    gttxreset.eq(1),
                    gttxpd.eq(1),
                    self.pllreset.eq(1),
                ]
                m.d.comb += [
                    init_delay.wait.eq(1)
                ]
                with m.If(init_delay.done):
                    m.next = "WAIT-PLL-RESET"
            with m.State("WAIT-PLL-RESET"):
                m.d.comb += gttxreset.eq(1)
                with m.If(plllock):
                    m.next = "WAIT-INIT-DELAY"
            
            with m.State("WAIT-INIT-DELAY"):
                m.d.comb += [
                    init_delay.wait.eq(1)
                ]
                with m.If(init_delay.done):
                    m.next = "WAIT-GTP-RESET"

            with m.State("WAIT-GTP-RESET"):
                m.d.comb += txuserrdy.eq(1)
                with m.If(txresetdone):
                    m.next = "READY"
            
            with m.State("READY"):
                m.d.comb += [
                    txuserrdy.eq(1),
                    txdlyen.eq(1),
                    self.done.eq(1),
                ]
                with m.If(self.restart):
                    m.next = "POWER-DOWN"

            m.d.comb += self.debug.eq(
                    #fsm.ongoing("WAIT-GTP-RESET") 
                    gttxreset
                   )

        if False:
            # FSM watchdog / restart
            watchdog = WaitTimer(int(1e-3*self.sys_clk_freq))
            m.submodules += watchdog
            m.d.comb += [
                watchdog.wait.eq(~fsm.reset & ~self.done),
                fsm.reset.eq(self.restart | watchdog.done)
            ]

        return m

# GTP RX Init --------------------------------------------------------------------------------------

class GTPRXInit(Elaboratable):
    def __init__(self, sys_clk_freq, buffer_enable):
        self.sys_clk_freq = sys_clk_freq
        self.buffer_enable = buffer_enable

        self.done            = Signal()
        self.restart         = Signal()

        # GTP signals
        self.plllock         = Signal()
        self.gtrxreset       = Signal()
        self.gtrxpd          = Signal()
        self.rxresetdone     = Signal()
        self.rxdlysreset     = Signal()
        self.rxdlysresetdone = Signal()
        self.rxphalign       = Signal()
        self.rxuserrdy       = Signal()
        self.rxsyncdone      = Signal()
        self.rxpmaresetdone  = Signal()

        self.drp_clk = Signal()
        self.drp_en = Signal()
        self.drp_we = Signal()
        self.drp_rdy = Signal()
        self.drp_addr = Signal(9)
        self.drp_di = Signal(16)
        self.drp_do = Signal(16)

        # # #
    def elaborate(self, platform):
        m = Module()

        rxpmaresetdone = Signal()
        m.submodules += FFSynchronizer(self.rxpmaresetdone, rxpmaresetdone)
        rxpmaresetdone_r = Signal()
        m.d.sync += rxpmaresetdone_r.eq(rxpmaresetdone)

        # Double-latch transceiver asynch outputs
        plllock         = Signal()
        rxresetdone     = Signal()
        rxdlysresetdone = Signal()
        rxsyncdone      = Signal()
        m.submodules += [
            FFSynchronizer(self.plllock, plllock),
            FFSynchronizer(self.rxresetdone, rxresetdone),
            FFSynchronizer(self.rxdlysresetdone, rxdlysresetdone),
            FFSynchronizer(self.rxsyncdone, rxsyncdone)
        ]

        # Deglitch FSM outputs driving transceiver asynch inputs
        gtrxreset   = Signal()
        gtrxpd      = Signal()
        rxdlysreset = Signal()
        rxphalign   = Signal()
        rxuserrdy   = Signal()
        m.d.sync += [
            self.gtrxreset.eq(gtrxreset),
            self.gtrxpd.eq(gtrxpd),
            self.rxdlysreset.eq(rxdlysreset),
            self.rxphalign.eq(rxphalign),
            self.rxuserrdy.eq(rxuserrdy)
        ]

        # Wait 500ns after configuration before releasing GTP reset (to follow AR43482)
        init_delay = WaitTimer(int(500e-9*self.sys_clk_freq))
        m.submodules += init_delay
        m.d.comb += init_delay.wait.eq(1)

        drpval = Signal(16)

        m.d.comb += [
            self.drp_addr.eq(0x011),
            self.drp_clk.eq(ClockSignal())
        ]

        with m.FSM(reset="POWER-DOWN"):
            with m.State("POWER-DOWN"):
                m.d.comb += [
                    gtrxreset.eq(1),
                    gtrxpd.eq(1),
                ]
                m.next = "WAIT-INIT-DELAY"

            with m.State("WAIT-INIT-DELAY"):
                m.d.comb += gtrxreset.eq(1)
                with m.If(plllock & init_delay.done):
                    m.next = "DRP-READ-ISSUE"

            with m.State("DRP-READ-ISSUE"):
                m.d.comb += [
                    gtrxreset.eq(1),
                    self.drp_en.eq(1)
                ]
                m.next = "DRP-READ-WAIT"

            with m.State("DRP-READ-WAIT"):
                m.d.comb += [
                    gtrxreset.eq(1),
                ]
                with m.If(self.drp_rdy):
                    m.d.sync += [
                        drpval.eq(self.drp_do)
                    ]
                    m.next = "DRP-MOD-ISSUE"
            
            with m.State("DRP-MOD-ISSUE"):
                m.d.comb += [
                    gtrxreset.eq(1),
                    self.drp_di.eq(drpval & 0xf7ff),
                    self.drp_en.eq(1),
                    self.drp_we.eq(1),
                ]
                m.next = "DRP-MOD-WAIT"

            with m.State("DRP-MOD-WAIT"):
                m.d.comb += [
                    gtrxreset.eq(1),
                ]
                with m.If(self.drp_rdy):
                    m.next = "WAIT_PMARST_FALL"

            with m.State("WAIT_PMARST_FALL"):
                # TODO: Set rxuserrdy
                m.d.comb += [
                    rxuserrdy.eq(1),
                ]
                with m.If(rxpmaresetdone_r & ~rxpmaresetdone):
                    m.next = "DRP-RESTORE-ISSUE"

            with m.State("DRP-RESTORE-ISSUE"):
                m.d.comb += [
                    self.drp_di.eq(drpval),
                    self.drp_en.eq(1),
                    self.drp_we.eq(1),
                ]
                m.next = "DRP-RESTORE-WAIT"

            with m.State("DRP-RESTORE-WAIT"):
                with m.If(self.drp_rdy):
                    m.next = "WAIT-GTP-RESET"

            with m.State("WAIT-GTP-RESET"):
                m.d.comb += [
                    gtrxreset.eq(0),
                    rxuserrdy.eq(1),
                ]
                with m.If(rxresetdone):
                    with m.If(self.buffer_enable):
                        m.next = "READY"
                    with m.Else():
                        m.next = "ALIGN"
    
            with m.State("ALIGN"):
                m.d.comb += [
                    gtrxreset.eq(0),
                    rxuserrdy.eq(1),
                    rxdlysreset.eq(1),
                ]
                with m.If(rxdlysresetdone):
                    m.next = "WAIT_ALIGN_DONE"

            with m.State("WAIT_ALIGN_DONE"):
                m.d.comb += [
                    gtrxreset.eq(0),
                    rxuserrdy.eq(1),
                ]
                with m.If(rxsyncdone):
                    m.next = "READY"

            with m.State("READY"):
                m.d.comb += [
                    gtrxreset.eq(0),
                    rxuserrdy.eq(1),
                    self.done.eq(1),
                ]
                with m.If(self.restart):
                    m.next = "POWER-DOWN"

        # Don't know how to get the reset signal for a FSM
        if False:
            # FSM watchdog / restart
            watchdog = WaitTimer(int(4e-3*self.sys_clk_freq))
            m.submodules += watchdog
            m.d.comb += [
                watchdog.wait.eq(~fsm_reset & ~self.done),
                fsm_reset.eq(self.restart | watchdog.done)
            ]
        return m