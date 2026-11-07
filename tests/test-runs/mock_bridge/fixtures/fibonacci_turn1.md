File: package.json


```json

{
  "name": "modular-fibonacci",
  "version": "1.0.0",
  "description": "A modular Node.js Fibonacci project",
  "main": "src/cli.js",
  "scripts": {
    "start": "node src/cli.js"
  },
  "keywords": [
    "fibonacci",
    "node"
  ],
  "author": "",
  "license": "ISC"
}


```


File: src/fibonacci.js


```javascript

/**
 * Calculates the n-th Fibonacci number iteratively.
 * @param {number} n - The non-negative integer index.
 * @returns {number} The n-th Fibonacci number.
 */
function fibonacci(n) {
  if (typeof n !== 'number' || !Number.isInteger(n) || n < 0) {
    throw new Error('Argument must be a non-negative integer.');
  }
  if (n === 0) return 0;
  if (n === 1) return 1;

  let prev2 = 0;
  let prev1 = 1;
  let current = 0;

  for (let i = 2; i <= n; i++) {
    current = prev1 + prev2;
    prev2 = prev1;
    prev1 = current;
  }

  return current;
}

/**
 * Calculates the n-th Fibonacci number recursively.
 * @param {number} n - The non-negative integer index.
 * @returns {number} The n-th Fibonacci number.
 */
function fibonacciRecursive(n) {
  if (typeof n !== 'number' || !Number.isInteger(n) || n < 0) {
    throw new Error('Argument must be a non-negative integer.');
  }
  if (n === 0) return 0;
  if (n === 1) return 1;

  return fibonacciRecursive(n - 1) + fibonacciRecursive(n - 2);
}

module.exports = {
  fibonacci,
  fibonacciRecursive
};


```


File: src/cli.js


```javascript

const { fibonacci } = require('./fibonacci');

function main() {
  const args = process.argv.slice(2);
  const n = args.length > 0 ? parseInt(args[0], 10) : 10;

  if (isNaN(n) || n < 0) {
    console.error('Error: Please provide a valid non-negative integer for n.');
    process.exit(1);
  }

  console.log(`Generating Fibonacci sequence of ${n} terms:`);
  const sequence = [];
  for (let i = 0; i < n; i++) {
    sequence.push(fibonacci(i));
  }
  console.log(sequence.join(', '));
}

main();


```
