function deepClone(value) {
  return JSON.parse(JSON.stringify(value ?? null))
}

export function detectMediaFields(schema, path = []) {
  const items = []

  if (Array.isArray(schema)) {
    if (schema.length > 0) {
      items.push(...detectMediaFields(schema[0], [...path, '[0]']))
    }
    return items
  }

  if (!schema || typeof schema !== 'object') {
    return items
  }

  if (Object.prototype.hasOwnProperty.call(schema, 'media_id')) {
    items.push({
      path: path.join('.').replace('.[0]', '[0]'),
      sample: schema,
    })
  }

  Object.entries(schema).forEach(([key, value]) => {
    items.push(...detectMediaFields(value, [...path, key]))
  })

  return items
}

function tokenizeSchemaPath(path) {
  return path
    .split('.')
    .filter(Boolean)
    .flatMap((part) => {
      const tokens = []
      const matcher = /([^[\]]+)|\[(\d+)\]/g
      let match = matcher.exec(part)
      while (match) {
        tokens.push(match[1] ?? Number(match[2]))
        match = matcher.exec(part)
      }
      return tokens
    })
}

export function getValueAtPath(value, path) {
  const tokens = tokenizeSchemaPath(path)
  let current = value
  for (const token of tokens) {
    if (current == null) return null
    current = current[token]
  }
  return current ?? null
}

export function setValueAtPath(value, path, nextValue) {
  const tokens = tokenizeSchemaPath(path)
  const clone = deepClone(value)
  if (tokens.length === 0) return clone

  let current = clone
  tokens.forEach((token, index) => {
    const isLast = index === tokens.length - 1
    if (isLast) {
      current[token] = nextValue
      return
    }
    const nextToken = tokens[index + 1]
    if (current[token] == null || typeof current[token] !== 'object') {
      current[token] = typeof nextToken === 'number' ? [] : {}
    }
    current = current[token]
  })
  return clone
}

export function formatMediaFieldLabel(path) {
  const tokens = tokenizeSchemaPath(path).map((token) => String(token))
  const last = tokens[tokens.length - 1] || 'image'
  return last
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

export function applyMediaFieldValue(currentValue, media) {
  const nextValue = {
    ...(currentValue && typeof currentValue === 'object' && !Array.isArray(currentValue)
      ? currentValue
      : {}),
  }

  const mediaId = media.id || media.media_id
  nextValue.media_id = mediaId

  if (Object.prototype.hasOwnProperty.call(nextValue, 'src')) nextValue.src = media.url || ''
  if (Object.prototype.hasOwnProperty.call(nextValue, 'url')) nextValue.url = media.url || ''

  const nextName = media.filename || ''
  if (Object.prototype.hasOwnProperty.call(nextValue, 'file_name')) nextValue.file_name = nextName
  else if (Object.prototype.hasOwnProperty.call(nextValue, 'filename')) nextValue.filename = nextName
  else if (Object.prototype.hasOwnProperty.call(nextValue, 'name')) nextValue.name = nextName

  const nextAlt = media.alt_text || nextName
  if (Object.prototype.hasOwnProperty.call(nextValue, 'alt_text')) nextValue.alt_text = nextAlt
  else if (Object.prototype.hasOwnProperty.call(nextValue, 'altText')) nextValue.altText = nextAlt
  else if (Object.prototype.hasOwnProperty.call(nextValue, 'alt')) nextValue.alt = nextAlt

  return nextValue
}
