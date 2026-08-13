# Firmware and embedded systems

Words for code that runs on a device with a fixed budget of memory, time and
power, where a fault has no operator to report itself to.

Words only. Which definitions do any of this is read from your repository —
a template has never seen your code and cannot say what it does.

domain: running correctly on a device with fixed memory and no operator
domain: meeting a deadline every time rather than on average
domain: surviving power loss without corrupting what was stored

activity: initialise a peripheral
activity: configure a clock or a timer
activity: service an interrupt
activity: read a sensor
activity: drive an actuator or an output pin
activity: transfer over a bus
activity: pack or unpack a wire format
activity: allocate from a fixed pool
activity: feed or configure a watchdog
activity: enter or leave a low-power state
activity: write to non-volatile storage
activity: apply or verify a firmware update
activity: recover from a fault or reset

role: a register or a memory-mapped address
role: an interrupt handler
role: a ring buffer or a queue between contexts
role: a device driver
role: a state machine
role: a calibration constant
role: a boot or reset vector
