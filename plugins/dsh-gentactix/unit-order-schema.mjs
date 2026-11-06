/** Structured proposal only; runtime binds identity and validates semantics. */
export const unitOrderProperties = {
  order: {
    type: 'object', additionalProperties: false, required: ['action'],
    properties: {
      unit_id: { type: 'string' }, action: { type: 'string' },
      duration: { type: 'string', enum: ['next', 'until_arrived', 'until_turn'] },
      destination: {
        type: 'object', additionalProperties: false, required: ['lat', 'lng'],
        properties: { lat: { type: 'number' }, lng: { type: 'number' } },
      },
      target_id: { type: 'string' }, air_pool: { type: 'string' },
      end_turn: { type: 'integer' },
      participation: { type: 'string', enum: ['withdraw', 'reenter'] },
    },
  },
  rationale: { type: 'string', minLength: 1, maxLength: 1000 },
  expected_effect: { type: 'string', minLength: 1, maxLength: 1000 },
};

const {end_turn, ...plannerOrderFields} = unitOrderProperties.order.properties;
export const plannerOrderProperties = {
  orders: {
    type: 'array', minItems: 1,
    items: {
      type: 'object', additionalProperties: false,
      required: ['unit_id', 'action', 'rationale', 'expected_effect'],
      properties: {
        ...plannerOrderFields,
        duration: {type: 'string', enum: ['next', 'until_arrived']},
        rationale: unitOrderProperties.rationale,
        expected_effect: unitOrderProperties.expected_effect,
      },
    },
  },
};
