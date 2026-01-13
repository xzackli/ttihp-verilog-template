# SPDX-FileCopyrightText: © 2024 Tiny Tapeout
# SPDX-License-Identifier: Apache-2.0

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge

def adc_miso(adc0, adc1, adc2, adc3):
    """Pack 4 ADC MISO bits into uio_in[3:0]"""
    return (adc3 << 3) | (adc2 << 2) | (adc1 << 1) | adc0

def get_bit(value, bit, width):
    return (value >> (width - 1 - bit)) & 1


def pack_bits(bits):
    # Pack LSB-first iterable of pin bits into an int
    value = 0
    for idx, bit in enumerate(bits):
        value |= (bit & 1) << idx
    return value

# serial clock waiters
async def wait_sclk_fall(dut):
    while dut.uo_out.value[0] == 0:
        await RisingEdge(dut.clk)
    while dut.uo_out.value[0] == 1:
        await RisingEdge(dut.clk)

async def wait_sclk_rise(dut):
    while dut.uo_out.value[0] == 1:
        await RisingEdge(dut.clk)
    while dut.uo_out.value[0] == 0:
        await RisingEdge(dut.clk)

async def run_adc_test(dut, cfg_bits_pins, cfg_null_pins, adc_patterns, cfg_clkdiv_pins, cfg_msb_pin=0):
    dut._log.info("Start")

    clock = Clock(dut.clk, 50, unit="ns")
    cocotb.start_soon(clock.start())

    # Reset
    dut._log.info("Reset")
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)

    cfg_bits = pack_bits(cfg_bits_pins)
    cfg_null = pack_bits(cfg_null_pins)
    cfg_clkdiv = pack_bits(cfg_clkdiv_pins)

    width = ((cfg_msb_pin << 4) | cfg_bits) + 1
    dut.ui_in.value = (cfg_clkdiv << 6) | (cfg_null << 4) | cfg_bits
    base_uio_in = cfg_msb_pin << 7

    cs_n = dut.uo_out.value[1]
    assert cs_n == 0, "CS_N should be active low during ADC sampling phase"
    dut.rst_n.value = 1

    dut._log.info("Test project behavior")

    # Feed cfg_null + width cycles (nulls + data bits)
    # HW samples on rising edge when its internal cycle >= cfg_null. At loop
    # index c, the HW cycle is (c + 1) after wait_sclk_fall. Therefore the
    # first data bit should be driven when (c + 1) == cfg_null, i.e.,
    # c = cfg_null - 1. Null cycles are those with c < cfg_null - 1.
    total_cycles = cfg_null + width
    drive_cycle = 0

    def drive_for_cycle(c):
        if c < cfg_null:
            dut.uio_in.value = base_uio_in | adc_miso(0, 0, 0, 0)
        else:
            bit = c - cfg_null
            dut.uio_in.value = base_uio_in | adc_miso(
                get_bit(adc_patterns[0], bit, width),
                get_bit(adc_patterns[1], bit, width),
                get_bit(adc_patterns[2], bit, width),
                get_bit(adc_patterns[3], bit, width)
            )

    drive_for_cycle(drive_cycle)

    for cycle in range(total_cycles):
        assert dut.uo_out.value[1] == 0, "CS_N should remain active low during ADC sampling phase"
        assert dut.uio_out.value[7] == 0, "TX MOSI should be low during ADC sampling phase"

        await wait_sclk_rise(dut)
        await wait_sclk_fall(dut)

        drive_cycle += 1
        if drive_cycle < total_cycles:
            drive_for_cycle(drive_cycle)

    dut._log.info("Reading TX data at full clock speed...")
    for i in range(width * 4):
        adc_idx = i // width
        bit_idx = i % width
        tx_mosi = dut.uo_out.value[3]
        expected = get_bit(adc_patterns[adc_idx], bit_idx, width)
        assert tx_mosi == expected, f"TX bit {i}: ADC{adc_idx} bit {bit_idx} mismatch: got {tx_mosi}, expected {expected}"
        await RisingEdge(dut.clk)


@cocotb.test()
async def test_project_12bit(dut):
    cfg_bits = (1, 1, 0, 1)  # ui[3:0] -> 12-bit (11 + 1)
    cfg_null = (0, 1)  # ui[5:4] -> 2 null
    adc_patterns = [
        0b111111111111,
        0b000000000000,
        0b101010101010,
        0b110000110011,
    ]
    await run_adc_test(dut, cfg_bits, cfg_null, adc_patterns, cfg_clkdiv_pins=(0, 0))


@cocotb.test()
async def test_project_14bit(dut):
    cfg_bits = (1, 0, 1, 1)  # ui[3:0] -> 14-bit (13 + 1)
    cfg_null = (0, 1)  # ui[5:4] -> 2 null
    adc_patterns = [
        0b11111111111111,
        0b00000000000000,
        0b10101010101010,
        0b11000011001100,
    ]
    await run_adc_test(dut, cfg_bits, cfg_null, adc_patterns, cfg_clkdiv_pins=(1, 0))



@cocotb.test()
async def test_project_12bit_null0(dut):
    cfg_bits = (1, 1, 0, 1)  # ui[3:0] -> 12-bit (11 + 1)
    cfg_null = (0, 0)  # ui[5:4] -> 0 null
    adc_patterns = [
        0b111111000000,
        0b000000111111,
        0b101010010101,
        0b110011001100,
    ]
    await run_adc_test(dut, cfg_bits, cfg_null, adc_patterns, cfg_clkdiv_pins=(1, 1))


@cocotb.test()
async def test_project_14bit_null0(dut):
    cfg_bits = (1, 0, 1, 1)  # ui[3:0] -> 14-bit (13 + 1)
    cfg_null = (0, 0)  # ui[5:4] -> 0 null
    adc_patterns = [
        0b11111111110000,
        0b00000000001111,
        0b10101010100101,
        0b11001100110011,
    ]
    await run_adc_test(dut, cfg_bits, cfg_null, adc_patterns, cfg_clkdiv_pins=(1, 1))


@cocotb.test()
async def test_project_24bit_null0(dut):
    cfg_bits = (1, 1, 1, 0)  # ui[3:0] -> 24-bit (23 + 1, msb_pin=1)
    cfg_null = (0, 0)  # ui[5:4] -> 0 null
    adc_patterns = [
        0b111111111111000000000000,
        0b000000000000111111111111,
        0b101010101010100101010101,
        0b110011001100110011001100,
    ]
    await run_adc_test(dut, cfg_bits, cfg_null, adc_patterns, cfg_clkdiv_pins=(1, 1), cfg_msb_pin=1)


@cocotb.test()
async def test_project_24bit_null2(dut):
    cfg_bits = (1, 1, 1, 0)  # ui[3:0] -> 24-bit (23 + 1, msb_pin=1)
    cfg_null = (0, 1)  # ui[5:4] -> 2 null
    adc_patterns = [
        0b111111111111111100000000,
        0b000000000000000011111111,
        0b101010101010101001010101,
        0b110011001100110011001100,
    ]
    await run_adc_test(dut, cfg_bits, cfg_null, adc_patterns, cfg_clkdiv_pins=(1, 1), cfg_msb_pin=1)
