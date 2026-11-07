File: src/memoizedFibonacci.js


```javascript

/**
 * Calculates the n-th Fibonacci number using memoization.
 * @param {number} n - The non-negative integer index.
 * @param {Map<number, number>} [cache=new Map()] - Optional cache for memoization.
 * @returns {number} The n-th Fibonacci number.
 */
function memoizedFibonacci(n, cache = new Map()) {
  if (typeof n !== 'number' || !Number.isInteger(n) || n < 0) {
    throw new Error('Argument must be a non-negative integer.');
  }
  if (n === 0) return 0;
  if (n === 1) return 1;

  if (cache.has(n)) {
    return cache.get(n);
  }

  const result = memoizedFibonacci(n - 1, cache) + memoizedFibonacci(n - 2, cache);
  cache.set(n, result);
  return result;
}

/**
 * Generator function that yields a Fibonacci sequence up to a given limit.
 * @param {number} limit - The number of terms to generate.
 * @yields {number} The next Fibonacci number in the sequence.
 */
function* fibonacciSequence(limit) {
  if (typeof limit !== 'number' || !Number.isInteger(limit) || limit < 0) {
    throw new Error('Limit must be a non-negative integer.');
  }

  let prev2 = 0;
  let prev1 = 1;

  for (let i = 0; i < limit; i++) {
    if (i === 0) {
      yield 0;
    } else if (i === 1) {
      yield 1;
    } else {
      const current = prev1 + prev2;
      prev2 = prev1;
      prev1 = current;
      yield current;
    }
  }
}

module.exports = {
  memoizedFibonacci,
  fibonacciSequence
};


```


File: src/benchmark.js


```javascript

const { fibonacci } = require('./fibonacci');
const { memoizedFibonacci } = require('./memoizedFibonacci');

const N = 40;

console.log(`=== Fibonacci Benchmark (N = ${N}) ===\n`);

console.time('Standard Fibonacci Time');
const standardResult = fibonacci(N);
console.timeEnd('Standard Fibonacci Time');
console.log(`Standard Result: ${standardResult}\n`);

console.time('Memoized Fibonacci Time');
const memoizedResult = memoizedFibonacci(N);
console.timeEnd('Memoized Fibonacci Time');
console.log(`Memoized Result: ${memoizedResult}\n`);


```
