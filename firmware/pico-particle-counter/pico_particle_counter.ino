#include <Arduino.h>
#include <Wire.h>

#include "hardware/pio.h"
#include "hardware/irq.h"
#include "hardware/gpio.h"
#include "hardware/sync.h"
#include "hardware/pio_instructions.h"

#define I2C_ADDR 0x17

#define I2C_SDA 4
#define I2C_SCL 5

// Channel order:
// A1, A2, A3, A4, B1, B2, B3, B4
static const uint8_t CHANNEL_PINS[8] = {
  22,  // A1
  21,  // A2
  20,  // A3
  19,  // A4
   6,  // B1
   8,  // B2
  10,  // B3
  12   // B4
};

volatile uint32_t counters[8] = {0};

// PIO program, written directly as instructions.
// Equivalent to:
//
// .wrap_target
//     wait 0 pin 0
//     wait 1 pin 0
//     irq wait rel 0
// .wrap
//
static const uint16_t pulse_counter_program_instructions[] = {
  (uint16_t)pio_encode_wait_pin(false, 0),
  (uint16_t)pio_encode_wait_pin(true,  0),
  (uint16_t)pio_encode_irq_wait(true, 0)
};

static const struct pio_program pulse_counter_program = {
  .instructions = pulse_counter_program_instructions,
  .length = 3,
  .origin = -1
};

void pack_u32_le(uint8_t *buf, uint32_t value) {
  buf[0] = (value >> 0)  & 0xFF;
  buf[1] = (value >> 8)  & 0xFF;
  buf[2] = (value >> 16) & 0xFF;
  buf[3] = (value >> 24) & 0xFF;
}

void onRequest() {
  uint32_t snapshot[8];
  uint8_t buffer[32];

  uint32_t irq_state = save_and_disable_interrupts();

  for (int i = 0; i < 8; i++) {
    snapshot[i] = counters[i];
  }

  restore_interrupts(irq_state);

  for (int i = 0; i < 8; i++) {
    pack_u32_le(&buffer[4 * i], snapshot[i]);
  }

  Wire.write(buffer, 32);
}

void pio0_irq0_handler() {
  for (int sm = 0; sm < 4; sm++) {
    if (pio_interrupt_get(pio0, sm)) {
      counters[sm]++;
      pio_interrupt_clear(pio0, sm);
    }
  }
}

void pio1_irq0_handler() {
  for (int sm = 0; sm < 4; sm++) {
    if (pio_interrupt_get(pio1, sm)) {
      counters[4 + sm]++;
      pio_interrupt_clear(pio1, sm);
    }
  }
}

void setup_one_counter(PIO pio, uint sm, uint offset, uint gpio) {
  gpio_init(gpio);
  gpio_disable_pulls(gpio);

  pio_gpio_init(pio, gpio);
  pio_sm_set_consecutive_pindirs(pio, sm, gpio, 1, false);

  pio_sm_config c = pio_get_default_sm_config();

  sm_config_set_in_pins(&c, gpio);

  // Program length = 3 instructions.
  // Wrap from instruction offset+2 back to offset+0.
  sm_config_set_wrap(&c, offset + 0, offset + 2);

  pio_sm_init(pio, sm, offset, &c);
  pio_sm_set_enabled(pio, sm, true);
}

void setup_pio_counters() {
  uint offset0 = pio_add_program(pio0, &pulse_counter_program);
  uint offset1 = pio_add_program(pio1, &pulse_counter_program);

  irq_set_exclusive_handler(PIO0_IRQ_0, pio0_irq0_handler);
  irq_set_exclusive_handler(PIO1_IRQ_0, pio1_irq0_handler);

  for (int sm = 0; sm < 4; sm++) {
    pio_set_irq0_source_enabled(pio0, (pio_interrupt_source_t)(pis_interrupt0 + sm), true);
    pio_set_irq0_source_enabled(pio1, (pio_interrupt_source_t)(pis_interrupt0 + sm), true);
  }

  irq_set_enabled(PIO0_IRQ_0, true);
  irq_set_enabled(PIO1_IRQ_0, true);

  setup_one_counter(pio0, 0, offset0, CHANNEL_PINS[0]);  // A1 GPIO22
  setup_one_counter(pio0, 1, offset0, CHANNEL_PINS[1]);  // A2 GPIO21
  setup_one_counter(pio0, 2, offset0, CHANNEL_PINS[2]);  // A3 GPIO20
  setup_one_counter(pio0, 3, offset0, CHANNEL_PINS[3]);  // A4 GPIO19

  setup_one_counter(pio1, 0, offset1, CHANNEL_PINS[4]);  // B1 GPIO6
  setup_one_counter(pio1, 1, offset1, CHANNEL_PINS[5]);  // B2 GPIO8
  setup_one_counter(pio1, 2, offset1, CHANNEL_PINS[6]);  // B3 GPIO10
  setup_one_counter(pio1, 3, offset1, CHANNEL_PINS[7]);  // B4 GPIO12
}

void setup_i2c() {
  Wire.setSDA(I2C_SDA);
  Wire.setSCL(I2C_SCL);

  Wire.begin(I2C_ADDR);
  Wire.onRequest(onRequest);
}

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);

  setup_pio_counters();
  setup_i2c();
}

void loop() {
  digitalWrite(LED_BUILTIN, HIGH);
  delay(100);
  digitalWrite(LED_BUILTIN, LOW);
  delay(900);
}