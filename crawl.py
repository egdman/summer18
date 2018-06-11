#!/usr/bin/env python3
import sys
import os
import re
import shutil
import asyncio
import aiohttp
from time import clock
from itertools import chain
from urllib import request, parse
from html.parser import HTMLParser
from argparse import ArgumentParser
from asyncio import Queue
import multiprocessing as mp


def canonize(url):
  return re.sub(r'/+$', '', url.strip()) + '/'

def defrag(url):
  return parse.urlunsplit(parse.urlsplit(url)[:3] + ('',''))

def makeFilename(url):
  url = canonize(url)[:-1]
  return re.sub(r'/', '..', re.sub(r'^(\w*?)://', '', url))


class FindLinks(HTMLParser):
  def __init__(self):
    super(FindLinks, self).__init__()
    self.foundLinks = []


  def handle_starttag(self, _, attrs):
    self.foundLinks.extend(
      (value.strip() for name, value in attrs if value and name in ("href", "src")))


def canDecode(data, enc):
  def _canDecode(chunk):
    try:
      chunk.decode(enc)
      return True
    except UnicodeDecodeError:
      return False

  sz = len(data)
  for chunkSz in range(sz, sz - 5, -1):
    if _canDecode(data[:chunkSz]): return True
  return False


def doDecode(data, enc):
  try:
    return data.decode(enc)
  except UnicodeDecodeError:
    return ""


async def downloadAsync(istream, filename):
  chunkSz = 1024

  firstChunk = await istream.content.read(chunkSz)
  if not canDecode(firstChunk, "utf-8"):
    return bytes()

  fullContent = bytes()
  with open(filename, 'wb') as ostream:
    ostream.write(firstChunk)
    fullContent += firstChunk
    while True:
      chunk = await istream.content.read(chunkSz)
      if not chunk:
        break
      ostream.write(chunk)
      fullContent += chunk

  return fullContent


async def download_noexcept(url, session, filename):
  try:
    page = await session.get(url)

    try:
      return await downloadAsync(page, filename)
    finally:
      page.close()

  except Exception as ex:
    return None


async def fetchAsync(url, eventLoop, filename):
  async with aiohttp.ClientSession(loop = eventLoop) as session:
    return url, await download_noexcept(url, session, filename)


def filenames(inputPath):
  for _, _, filenames in os.walk(inputPath):
    for filename in filenames:
      yield filename


class Spider(object):
  def __init__(self, rootUrl, rootDir, tempDir):
    self.root = rootUrl
    self.rootDir = rootDir
    self.tempDir = tempDir

    self.linkQueue = mp.Queue()
    self.toParse = mp.Queue()
    self.pending = set()
    self.down = set(filenames(self.rootDir))

    # read cached links
    uniqLinks = set([rootUrl])
    try:
      for linkFile in filenames(self.tempDir):
        if not linkFile.endswith(".links"):
          continue
        if linkFile[:-6] not in self.down:
          continue

        with open(os.path.join(self.tempDir, linkFile), 'r') as stream:
          for link in stream.read().strip().splitlines():
            uniqLinks.add(link)

    except OSError:
      pass

    for link in uniqLinks:
      if makeFilename(link) not in self.down:
        self.linkQueue.put_nowait(link)


  def parseText(self, rootUrl, rootDir, tempDir):
    while True:
      url, content = self.toParse.get()
      text = doDecode(content, "utf-8")
      parser = FindLinks()
      parser.feed(text)
      absLinks = (defrag(parse.urljoin(url, link)) for link in parser.foundLinks)
      absLinks = set(link for link in absLinks if os.path.commonprefix((link, rootUrl)) == rootUrl)

      # write links to disk
      filename = makeFilename(url)
      tempFilename = os.path.join(tempDir, filename)
      linkFilename = tempFilename + ".links"
      with open(linkFilename, "w") as stream:
        stream.write('\n'.join(absLinks))
    
      # rename temp file to permanent
      try:
        shutil.move(tempFilename, os.path.join(rootDir, filename))
      except OSError:
        pass

      for link in absLinks:
        self.linkQueue.put_nowait(link)


  async def monitor(self):
    while True:
      await asyncio.sleep(2)
      print("{} down, {} pending".format(len(self.down), len(self.pending)))
  

  async def run(self, eventLoop):
    monitorTask = asyncio.ensure_future(self.monitor())
    # cleanTask = asyncio.ensure_future(self.cleanQueue())

    def whenDownloaded(task):
      thisLink, content = task.result()
      self.pending.remove(thisLink)
      if content:
        self.toParse.put_nowait((thisLink, content))

    parsers = list(mp.Process(target = self.parseText, args = (self.root, self.rootDir, self.tempDir)) for _ in range(4))
    for parser in parsers:
      parser.start()

    print("Starting")
    while True:
      await asyncio.sleep(.01)
      if len(self.pending) >= 100: # too many tasks
        continue

      if self.linkQueue.empty():
        continue

      link = defrag(self.linkQueue.get())
      if link not in self.pending and not os.path.exists(os.path.join(self.rootDir, makeFilename(link))):
        self.pending.add(link)
        tempFilename = os.path.join(self.tempDir, makeFilename(link))
        task = asyncio.ensure_future(fetchAsync(link, eventLoop, tempFilename))
        task.add_done_callback(whenDownloaded)

      # elif len(self.pending) == 0:
      #   break

      # else:
      #   await asyncio.sleep(.01)

    monitorTask.cancel()
    # cleanTask.cancel()
    print("{} down".format(len(self.down)))


def main():
  parser = ArgumentParser()
  parser.add_argument("url", type=str, help="URL to explore")

  args = parser.parse_args()
  rootUrl = canonize(args.url)  

  downloadTo = makeFilename(rootUrl)
  print("downloading to: " + downloadTo)
  if not os.path.exists(downloadTo):
      os.mkdir(downloadTo)

  tempDir = downloadTo + ".temp"
  if not os.path.exists(tempDir):
      os.makedirs(tempDir)

  def handler(loop, context):
    pass

  started = clock()
  spider = Spider(rootUrl, downloadTo, tempDir)
  loop = asyncio.get_event_loop()
  loop.set_exception_handler(handler)
  try:
    loop.run_until_complete(spider.run(loop))

    # cleanup temp directory
    try:
      shutil.rmtree(tempDir)
    except OSError as ex:
      print(ex)

    print("done")
  except KeyboardInterrupt as ex:
    loop.call_exception_handler({"exception": ex})
    print("interrupted")

  print("{:.1f} seconds".format(clock() - started))


if __name__ == '__main__': main()
