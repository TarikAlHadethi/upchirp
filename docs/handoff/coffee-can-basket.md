# Coffee-can radar basket (proposal for Abdullah, checked 4 October 2026)

A starting basket for the first stage: the MIT coffee-can radar (2.4 GHz FMCW) plus test gear, bought from Canada. It is a proposal: Abdullah decides the design and checks it before ordering. Prices change; items marked "check" were not confirmed.

Source BOM: MIT OCW "Build a Small Radar System" (IAP 2011), BOM slides 13 to 15, revision GLC 8/28/2012: https://ocw.mit.edu/courses/res-ll-003-build-a-small-radar-system-capable-of-sensing-range-doppler-and-synthetic-aperture-radar-imaging-january-iap-2011/pages/projects/

## Decide first

1. **The VCO is discontinued.** ZX95-2536C+ became ZX95-2536C-S+, marked "not recommended for new designs", no price, not at Digi-Key or Mouser. Email sales@minicircuits.com for remaining stock. Fallback: ROS-2536C-119+ (surface-mount VCO, 2315 to 2536 MHz, in the catalog), which needs a small PCB with SMA connectors (price: check).
2. **The XR-2206 ramp generator is obsolete** (its XR2209 replacement too). Options: an XR2206 clone kit (Amazon.ca, check), or a microcontroller with a DAC.
3. **Test gear:** if the university lab has a network analyser and a spectrum analyser, skip both instruments below (saves about CAD 530 to 690).
4. **Is the 2.4 GHz coffee-can stage still worth it** given the VCO, or go straight to 5.8 GHz parts?

## Mini-Circuits direct (USD, shipping and duties to Canada: check)

| Item | Part | Qty | Unit | Notes |
| --- | --- | --- | --- | --- |
| VCO | ZX95-2536C-S+ | 1 | no price | see "Decide first" |
| LNA and power amp | ZX60-272LN-S+ | 2 | 119.47 | 0 in stock on the day checked |
| Mixer | ZX05-43MH-S+ | 1 | 73.06 | |
| Splitter | ZX10-2-42-S+ | 1 | 60.97 | 0 in stock on the day checked |
| 3 dB attenuator | VAT-3A+ | 1 | 21.07 | replaces VAT-3+ |
| SMA male-male barrel | SM-SM50+ | 4 | 8.46 | |
| 6 inch SMA cable | 086-6SM+ | 3 | 16.67 | the BOM's 086-12SM+ is the 12 inch one |

Subtotal about USD 478 (about CAD 660 at 1.38), without the VCO. The same modules are at Digi-Key Canada for about 35% more, out of stock until October to November 2026.

## Digi-Key Canada (CAD, duties included, free shipping over CAD 100)

| Item | Part | Qty | Unit | Notes |
| --- | --- | --- | --- | --- |
| Quad op-amp | LM324N | 1 | 0.91 | the OCW page's approved substitute for the MAX414 |
| 5 V regulator | L4940V5 | 1 | 4.19 | LM2940CT-5.0 out of stock until January 2027 |
| SMA bulkhead jack | Amphenol 901-9889-RFX (ARFX1227-ND) | 2 | 13.70 | |
| 6 dB and 10 dB attenuators | VAT-6A+, VAT-10A+ | 1 each | about 37 | check |
| Resistors, capacitors, trimmers, breadboard | per BOM slides 14 and 15 | about 40 lines | check | under USD 25 in 2012 |

Subtotal about CAD 120 to 160.

## Test gear (official sellers)

| Item | Model | Price | Where | 5.8 GHz? |
| --- | --- | --- | --- | --- |
| Spectrum analyser | tinySA Ultra+ ZS407 | about CAD 400 | Amazon.ca, Seeesii or AURSINC (both on the tinysa.org list) | yes, to 7.3 GHz |
| Network analyser | LiteVNA-64 | CAD 205 to 286 | Amazon.ca (official seller: check) | yes, to 6.3 GHz |

Skip the NanoVNA-H4: it stops at 1.5 GHz.

## Amazon.ca (CAD)

| Item | Pick | Price |
| --- | --- | --- |
| USB sound card with stereo line-in | Behringer UCA202 (B000KW2YEI) | 33.55 |
| SMA cables, 6 inch, 2-pack | Bingfu RG316 (B08DG7JFV7) | 10.99 |
| Bench power supply 30 V 5 A | NICE-POWER (B0C6D18SVW) | 45.11 |
| Ramp generator | XR2206 kit | check |
| 2 coffee cans | grocery store | about 5 |

Subtotal about CAD 95 to 110.

## Total

About CAD 1,400 to 1,650, without the VCO, Mini-Circuits shipping and duties, and the items marked "check". About CAD 870 to 960 if the lab lends the test gear.
