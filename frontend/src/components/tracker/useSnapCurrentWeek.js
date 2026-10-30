import { useEffect, useMemo, useState } from 'react'
import { useLocation, useSearchParams } from 'react-router-dom'
import { todayParts } from './trackerUtils'

function weekFromSearch(searchParams, today) {
  const year = Number(searchParams.get('year'))
  const month = Number(searchParams.get('month'))
  const week = Number(searchParams.get('week'))
  return {
    year: year >= 2000 && year <= 2100 ? year : today.year,
    month: month >= 1 && month <= 12 ? month : today.month,
    week: week >= 1 && week <= 4 ? week : today.week,
    cardId: searchParams.get('card') || '',
  }
}

export default function useSnapCurrentWeek() {
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const today = useMemo(() => todayParts(), [location.pathname])
  const requested = useMemo(
    () => weekFromSearch(searchParams, today),
    [searchParams, today],
  )
  const [year, setYear] = useState(requested.year)
  const [month, setMonth] = useState(requested.month)
  const [week, setWeek] = useState(requested.week)

  useEffect(() => {
    setYear(requested.year)
    setMonth(requested.month)
    setWeek(requested.week)
  }, [requested.year, requested.month, requested.week, location.pathname])

  return {
    today,
    year,
    month,
    week,
    setYear,
    setMonth,
    setWeek,
    focusCardId: requested.cardId,
  }
}
